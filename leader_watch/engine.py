# leader_watch/engine.py
"""Polling loop: KST time gating, holiday/weekend guard, phase dispatch, dedup."""
from __future__ import annotations

import datetime
import sys
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from leader_watch.alerts import (
    format_confirmation,
    format_early_candidate,
    format_leader_change,
    format_recovery,
    format_rejection,
    format_weakness,
)
from leader_watch.config import Config
from leader_watch.filters import is_excluded
from leader_watch.models import CandidateState, CandidateStatus, Phase, StockSnapshot
from leader_watch.notifiers.base import AlertNotifier
from leader_watch.providers.base import MarketDataProvider
from leader_watch.scoring import calculate_leader_score
from leader_watch.state_machine import (
    check_recovery,
    check_rejection,
    check_weakness,
    classify_gap,
    decide_early_candidate,
    detect_leader_change,
    evaluate_confirmation,
    update_open_recovery_tracking,
)
from leader_watch.store import AlertStore

# NOTE: manually maintained; must be refreshed each year (see README "휴장일 캘린더 갱신").
KRX_HOLIDAYS_2026: set[datetime.date] = {
    datetime.date(2026, 1, 1),
    datetime.date(2026, 2, 16),
    datetime.date(2026, 2, 17),
    datetime.date(2026, 2, 18),
    datetime.date(2026, 3, 1),
    datetime.date(2026, 3, 2),
    datetime.date(2026, 5, 5),
    datetime.date(2026, 5, 24),
    datetime.date(2026, 5, 25),
    datetime.date(2026, 6, 6),
    datetime.date(2026, 8, 15),
    datetime.date(2026, 9, 24),
    datetime.date(2026, 9, 25),
    datetime.date(2026, 9, 26),
    datetime.date(2026, 10, 3),
    datetime.date(2026, 10, 9),
    datetime.date(2026, 12, 25),
    datetime.date(2026, 12, 31),
}


KRX_HOLIDAY_YEARS: set[int] = {day.year for day in KRX_HOLIDAYS_2026}


def is_market_holiday_or_weekend(day: datetime.date, holidays: set[datetime.date]) -> bool:
    return day.weekday() >= 5 or day in holidays


def is_stale(snapshot: StockSnapshot, now: datetime.datetime, config: Config) -> bool:
    age_seconds = (now - snapshot.timestamp).total_seconds()
    return age_seconds > config.stale_threshold_seconds


def call_with_retry(fn: Callable[[], Any], max_retries: int = 3, base_delay_seconds: float = 0.5) -> Any:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - intentionally broad: any provider failure is retryable
            last_error = exc
            if attempt < max_retries - 1:
                time.sleep(base_delay_seconds * (2 ** attempt))
    assert last_error is not None
    raise last_error


class Engine:
    def __init__(self, provider: MarketDataProvider, notifier: AlertNotifier, config: Config, store: AlertStore) -> None:
        self.provider = provider
        self.notifier = notifier
        self.config = config
        self.store = store
        self.candidates: dict[str, CandidateState] = {}
        self.confirmed_theme_leader: dict[str, str] = {}  # theme -> leading code
        self.history: dict[str, list[StockSnapshot]] = {}
        self.rank_at_0925: dict[str, int] = {}
        # Session-day bookkeeping. `_session_date` is None until the first in-window
        # run_once(); when it changes, per-day state is reset and candidate rows already
        # persisted for that date are rehydrated (restart recovery).
        self._session_date: str | None = None
        # Once-per-day latch so the 09:30 confirmation phase fires on the FIRST tick
        # at-or-after confirmation_time instead of requiring an exact 09:30:00.000000 tick.
        self._confirmation_done = False
        self._warned_holiday_years: set[int] = set()

    def _should_send(self, code: str, alert_type: str, date: str, now: datetime.datetime, score: float) -> bool:
        last = self.store.last_alert(code, date, alert_type)
        if last is None:
            return True
        last_sent_at, last_score = last
        if (now - last_sent_at).total_seconds() >= self.config.alert_cooldown_seconds:
            return True
        return abs(score - last_score) >= self.config.score_renotify_delta

    def _send(self, code: str, alert_type: str, date: str, now: datetime.datetime, score: float, title: str, body: str) -> None:
        if not self._should_send(code, alert_type, date, now, score):
            return
        if self.notifier.send(title, body):
            self.store.record_alert(code, date, alert_type, score, now)

    def _theme_follower_count(self, snapshot: StockSnapshot, snapshots: list[StockSnapshot]) -> int:
        if snapshot.theme is None:
            return 0
        return sum(
            1 for other in snapshots
            if other.code != snapshot.code and other.theme == snapshot.theme and other.change_pct >= 2.0
        )

    def _warn_if_holiday_calendar_uncovered(self, day: datetime.date) -> None:
        """The holiday set is hand-maintained and fails *open* for uncovered years.

        We cannot guess future KRX holidays, so we do not block — but the operator must
        see that the "no alerts on holidays" guarantee is unverifiable for this date.
        """
        if day.year in KRX_HOLIDAY_YEARS or day.year in self._warned_holiday_years:
            return
        self._warned_holiday_years.add(day.year)
        print(
            f"[leader_watch] 경고: {day.year}년 휴장일 캘린더가 등록되어 있지 않습니다 "
            f"(등록된 연도: {sorted(KRX_HOLIDAY_YEARS)}). "
            "주말 외 휴장일에도 알림이 발송될 수 있으니 KRX_HOLIDAYS를 갱신하세요.",
            file=sys.stderr,
        )

    def _rehydrate_candidates(self, date: str) -> None:
        """Restore candidate rows already persisted for `date` after a mid-session restart.

        NOTE: this recovery is necessarily PARTIAL. `AlertStore.upsert_candidate` persists
        only name/phase/status/score, so `high_since_confirm`, `first_30min_low`, the streak
        counters (`early_candidate_streak`, `consecutive_open_recovery_fail`,
        `leader_change_streak`) and the snapshot history cannot be restored; they re-derive
        themselves from live ticks after the restart. The goal is only that a restarted
        engine does not treat previously rejected/confirmed stocks as brand new.
        """
        try:
            rows = self.store.load_today_candidates(date)
        except Exception as exc:  # noqa: BLE001 - restart recovery must never kill the run
            print(f"[leader_watch] 후보 상태 복구 실패 (빈 상태로 시작): {exc!r}", file=sys.stderr)
            return

        for code, row in rows.items():
            try:
                phase = Phase(row["phase"])
                status = CandidateStatus(row["status"])
            except ValueError:
                continue
            self.candidates[code] = CandidateState(
                code=code,
                name=row.get("name") or code,
                phase=phase,
                status=status,
                score=row.get("score") or 0.0,
            )
            if status in (CandidateStatus.CONFIRMED, CandidateStatus.WEAKENED, CandidateStatus.RECOVERED):
                # Confirmation already ran today; do not replay it after a restart.
                self._confirmation_done = True

    def _begin_session_day(self, date: str) -> None:
        if self._session_date == date:
            return
        self._session_date = date
        self.candidates = {}
        self.confirmed_theme_leader = {}
        self.history = {}
        self.rank_at_0925 = {}
        self._confirmation_done = False
        self._rehydrate_candidates(date)

    def run_once(self, now: datetime.datetime) -> None:
        self._warn_if_holiday_calendar_uncovered(now.date())
        if is_market_holiday_or_weekend(now.date(), KRX_HOLIDAYS_2026):
            return
        if now.time() < datetime.time(9, 0) or now.time() > self.config.monitoring_end_time:
            return

        date = now.strftime("%Y-%m-%d")
        self._begin_session_day(date)

        snapshots = call_with_retry(lambda: self.provider.get_snapshot(now))
        fresh = [s for s in snapshots if not is_stale(s, now, self.config) and not is_excluded(s)[0]]

        for snapshot in fresh:
            self.history.setdefault(snapshot.code, []).append(snapshot)

        if datetime.time(9, 24) <= now.time() <= datetime.time(9, 26):
            for snapshot in fresh:
                self.rank_at_0925[snapshot.code] = snapshot.market_trading_value_rank

        if now.time() < self.config.early_candidate_time:
            return

        if self.config.early_candidate_time <= now.time() < self.config.early_candidate_end_time:
            self._process_early_candidates(fresh, now, date)
        elif self.config.early_candidate_end_time <= now.time() < self.config.confirmation_time:
            self._process_validation(fresh, now, date)
        elif not self._confirmation_done and now.time() >= self.config.confirmation_time:
            # First tick at-or-after 09:30 owns the confirmation phase. Nothing can be in
            # CONFIRMED/WEAKENED status before this tick (confirmation is the only producer
            # of those states), so there is nothing for _process_monitoring to do here;
            # monitoring takes over from the next tick onward.
            self._process_confirmation(fresh, now, date)
            self._confirmation_done = True
        elif self._confirmation_done and now.time() >= self.config.confirmation_time:
            self._process_monitoring(fresh, now, date)

    def _process_early_candidates(self, snapshots: list[StockSnapshot], now: datetime.datetime, date: str) -> None:
        for snapshot in snapshots:
            history = self.history.get(snapshot.code, [snapshot])
            theme_rank = snapshot.theme_trading_value_rank
            prior = self.candidates.get(snapshot.code)
            prior_streak = prior.early_candidate_streak if prior else 0
            theme_followers = self._theme_follower_count(snapshot, snapshots)

            qualifies, breakdown, streak = decide_early_candidate(
                snapshot, history, snapshot.market_trading_value_rank, theme_rank,
                theme_followers, prior_streak, self.config,
            )

            state = prior or CandidateState(code=snapshot.code, name=snapshot.name, phase=Phase.EARLY_CANDIDATE, status=CandidateStatus.ACTIVE, score=breakdown.total)
            state.early_candidate_streak = streak
            state.score = breakdown.total
            state.market_rank = snapshot.market_trading_value_rank
            state.theme_rank = theme_rank
            self.candidates[snapshot.code] = state
            self.store.upsert_candidate(snapshot.code, date, snapshot.name, Phase.EARLY_CANDIDATE.value, state.status.value, breakdown.total, now)

            if qualifies:
                title, body = format_early_candidate(snapshot, breakdown, snapshot.market_trading_value_rank, theme_rank or 0)
                self._send(snapshot.code, "early_candidate", date, now, breakdown.total, title, body)

    def _process_validation(self, snapshots: list[StockSnapshot], now: datetime.datetime, date: str) -> None:
        for snapshot in snapshots:
            state = self.candidates.get(snapshot.code)
            if state is None or state.status != CandidateStatus.ACTIVE:
                continue

            update_open_recovery_tracking(state, snapshot)
            reason = check_rejection(state, snapshot, self.history.get(snapshot.code, [snapshot]), snapshot.market_trading_value_rank, snapshot.theme_trading_value_rank, self.config)

            if reason is not None:
                state.status = CandidateStatus.REJECTED
                self.store.upsert_candidate(snapshot.code, date, snapshot.name, Phase.VALIDATION.value, state.status.value, state.score, now)
                title, body = format_rejection(snapshot, state.score, reason)
                self._send(snapshot.code, "rejected", date, now, state.score, title, body)

    def _process_confirmation(self, snapshots: list[StockSnapshot], now: datetime.datetime, date: str) -> None:
        for snapshot in snapshots:
            state = self.candidates.get(snapshot.code)
            if state is None or state.status != CandidateStatus.ACTIVE:
                continue

            theme_followers = self._theme_follower_count(snapshot, snapshots)
            confirmed, breakdown, block_reason = evaluate_confirmation(
                snapshot, self.history.get(snapshot.code, [snapshot]), snapshot.market_trading_value_rank,
                snapshot.theme_trading_value_rank, self.rank_at_0925.get(snapshot.code), theme_followers, self.config,
            )
            state.score = breakdown.total

            if not confirmed:
                continue

            state.status = CandidateStatus.CONFIRMED
            state.phase = Phase.MONITORING
            state.high_since_confirm = snapshot.high_price
            state.first_30min_low = snapshot.low_price
            self.store.upsert_candidate(snapshot.code, date, snapshot.name, Phase.CONFIRMATION.value, state.status.value, breakdown.total, now)

            if snapshot.theme:
                self.confirmed_theme_leader[snapshot.theme] = snapshot.code

            rank_change = "확인 불가"
            prior_rank = self.rank_at_0925.get(snapshot.code)
            if prior_rank is not None:
                direction = "개선" if snapshot.market_trading_value_rank <= prior_rank else "악화"
                rank_change = f"{prior_rank}위 -> {snapshot.market_trading_value_rank}위 ({direction})"

            extras = {
                "gap_tier": classify_gap(snapshot.gap_from_prev_close_pct, self.config),
                "rank_change_vs_0910": rank_change,
                "theme_follower_count": theme_followers,
                "open_held": snapshot.vs_open_pct >= 0,
                "first_high_held": snapshot.current_price >= snapshot.high_price * 0.99,
                "pullback_volume_down": True,
                "rebreak_high": snapshot.current_price >= snapshot.high_price,
                "rank_maintained": prior_rank is None or snapshot.market_trading_value_rank <= prior_rank,
            }
            title, body = format_confirmation(snapshot, breakdown, extras)
            self._send(snapshot.code, "confirmed", date, now, breakdown.total, title, body)

    def _process_monitoring(self, snapshots: list[StockSnapshot], now: datetime.datetime, date: str) -> None:
        by_code = {s.code: s for s in snapshots}
        confirmed_states = {c: s for c, s in self.candidates.items() if s.status in (CandidateStatus.CONFIRMED, CandidateStatus.WEAKENED)}

        for code, state in confirmed_states.items():
            snapshot = by_code.get(code)
            if snapshot is None:
                continue

            if snapshot.high_price and (state.high_since_confirm is None or snapshot.high_price > state.high_since_confirm):
                state.high_since_confirm = snapshot.high_price

            overtaken = False
            if snapshot.theme and self.confirmed_theme_leader.get(snapshot.theme) not in (None, code):
                overtaken = True

            theme_followers = self._theme_follower_count(snapshot, snapshots)
            breakdown = calculate_leader_score(snapshot, self.history.get(code, [snapshot]), theme_followers, self.config)

            if state.status == CandidateStatus.CONFIRMED:
                reasons = check_weakness(state, snapshot, snapshot.market_trading_value_rank, snapshot.theme_trading_value_rank, self.config, overtaken_by=overtaken)
                if reasons:
                    prev_score, prev_rank, prev_theme_rank = state.score, state.market_rank, state.theme_rank
                    state.status = CandidateStatus.WEAKENED
                    drawdown = 0.0
                    if state.high_since_confirm:
                        drawdown = max(0.0, (state.high_since_confirm - snapshot.current_price) / state.high_since_confirm * 100)
                    # Capture the freshly recomputed score so the alert shows a real
                    # before/after delta (and so _should_send's score-delta logic works).
                    state.score = breakdown.total
                    self.store.upsert_candidate(code, date, snapshot.name, Phase.MONITORING.value, state.status.value, state.score, now)
                    title, body = format_weakness(
                        snapshot, prev_score, state.score, prev_rank or 0, snapshot.market_trading_value_rank,
                        prev_theme_rank or 0, snapshot.theme_trading_value_rank or 0, drawdown, reasons,
                    )
                    self._send(code, "weakened", date, now, state.score, title, body)
            elif state.status == CandidateStatus.WEAKENED:
                if check_recovery(state, snapshot, snapshot.market_trading_value_rank, snapshot.theme_trading_value_rank, breakdown, self.config):
                    # RECOVERED is a transient marker for "send the recovery alert", not a
                    # resting state: we fold straight back to CONFIRMED so the stock stays
                    # inside the monitoring / leader-change filters and can weaken again.
                    state.status = CandidateStatus.CONFIRMED
                    state.score = breakdown.total
                    self.store.upsert_candidate(code, date, snapshot.name, Phase.MONITORING.value, state.status.value, state.score, now)
                    title, body = format_recovery(snapshot, breakdown.total)
                    self._send(code, "recovered", date, now, state.score, title, body)

            state.market_rank = snapshot.market_trading_value_rank
            state.theme_rank = snapshot.theme_trading_value_rank

        self._detect_leader_changes(by_code, now, date)

    def _detect_leader_changes(self, by_code: dict[str, StockSnapshot], now: datetime.datetime, date: str) -> None:
        by_theme: dict[str, list[str]] = {}
        for code, state in self.candidates.items():
            if state.status not in (CandidateStatus.CONFIRMED, CandidateStatus.WEAKENED):
                continue
            snapshot = by_code.get(code)
            if snapshot is None or snapshot.theme is None:
                continue
            by_theme.setdefault(snapshot.theme, []).append(code)

        for theme, codes in by_theme.items():
            leader_code = self.confirmed_theme_leader.get(theme)
            if leader_code is None or leader_code not in codes:
                continue
            for code in codes:
                if code == leader_code:
                    continue
                leader_state = self.candidates[leader_code]
                challenger_state = self.candidates[code]
                leader_snap = by_code[leader_code]
                challenger_snap = by_code[code]
                confirmed, reasons = detect_leader_change(
                    leader_state, challenger_state, leader_snap, challenger_snap,
                    challenger_snap.market_trading_value_rank, leader_snap.market_trading_value_rank,
                )
                if confirmed:
                    self.confirmed_theme_leader[theme] = code
                    title, body = format_leader_change(
                        theme, now.strftime("%Y-%m-%d %H:%M:%S"), leader_snap.name, leader_code,
                        challenger_snap.name, code, leader_snap.market_trading_value_rank,
                        challenger_snap.market_trading_value_rank, reasons,
                    )
                    self._send(code, "leader_change", date, now, challenger_state.score, title, body)

    def _now(self) -> datetime.datetime:
        """Current naive KST wall clock. Seam so tests can drive `run()` deterministically."""
        return datetime.datetime.now(ZoneInfo(self.config.market_timezone)).replace(tzinfo=None)

    def run(self) -> None:
        while True:
            now = self._now()
            try:
                self.run_once(now)
            except NotImplementedError:
                # A missing provider implementation is a configuration error, not a
                # transient failure — retrying every 2s for an hour helps nobody.
                raise
            except Exception as exc:  # noqa: BLE001 - one bad tick must not kill the session
                print(
                    f"[leader_watch] {now:%H:%M:%S} 폴링 중 오류 발생, 다음 주기로 계속합니다: {exc!r}",
                    file=sys.stderr,
                )
            if now.time() > self.config.monitoring_end_time:
                break
            time.sleep(self.config.poll_interval_seconds)
