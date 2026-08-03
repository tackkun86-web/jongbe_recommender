import recommender
import notifier


def main():
    result = recommender.run_analysis()
    notifier.notify(result)


if __name__ == "__main__":
    main()
