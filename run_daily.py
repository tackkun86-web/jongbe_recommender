import sys

import recommender
import notifier


def main():
    session = sys.argv[1] if len(sys.argv) > 1 else "close"
    result = recommender.run_analysis(session=session)
    notifier.notify(result)


if __name__ == "__main__":
    main()
