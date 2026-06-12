import argparse
import sys

from weather_report import (
    DEFAULT_OUTPUT_FILE,
    create_weather_report_from_text,
    create_weather_report_interactive,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="地名と時間を含む自然文から天気情報を作成します。"
    )
    parser.add_argument(
        "request",
        nargs="*",
        help="例: 東京の今日の天気 / 大阪の明日の天気 / 札幌の今の天気 / パリの明後日の天気",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help="読み上げ用テキストの保存先",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        if args.request:
            request_text = " ".join(args.request)
            speech_text, result = create_weather_report_from_text(
                request_text,
                output_file=args.output,
            )
            if speech_text is None:
                print(result)
                print("もう一度入力してください。")
                speech_text, result = create_weather_report_interactive(
                    output_file=args.output,
                )
            print(speech_text)
            print(f"保存しました: {result}")
        else:
            while True:
                speech_text, result = create_weather_report_interactive(
                    output_file=args.output,
                )
                print(speech_text)
                print(f"保存しました: {result}")
                print()
    except KeyboardInterrupt:
        print()
        print("終了します。")
        return 0
    except Exception as error:
        print(f"天気の取得に失敗しました: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
