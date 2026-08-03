import recommender
import notifier
import scheduler


def main():
    result = recommender.run_analysis()
    notifier.notify(result)
    scheduler.start()


if __name__ == "__main__":
    main()
