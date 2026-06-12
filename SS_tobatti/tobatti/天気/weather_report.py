import argparse
import os

import requests


DEFAULT_LATITUDE = 35.639249
DEFAULT_LONGITUDE = 139.29911


def save_current_weather_speech(
    api_key,
    latitude=DEFAULT_LATITUDE,
    longitude=DEFAULT_LONGITUDE,
    output_file="weather_speech.txt",
):
    endpoint = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": latitude,
        "lon": longitude,
        "appid": api_key,
        "lang": "ja",
        "units": "metric",
    }

    print(f"緯度 {latitude}, 経度 {longitude} の現在の天気を取得しています...")

    try:
        response = requests.get(endpoint, params=params, timeout=10)
    except requests.exceptions.RequestException as error:
        print(f"ネットワークエラーが発生しました: {error}")
        return False

    if response.status_code != 200:
        print(f"APIリクエストに失敗しました。ステータスコード: {response.status_code}")
        print(f"レスポンス内容: {response.text}")
        return False

    data = response.json()
    weather = data["weather"][0]["description"]
    temperature = round(data["main"]["temp"])
    location_name = data.get("name") or "指定地点"
    speech_text = f"{location_name}付近の現在の天気は{weather}。気温は{temperature}度だよ。"

    output_path = os.path.abspath(output_file)
    print("天気情報の読み上げテキストを作成しました。")

    with open(output_path, "w", encoding="utf-8") as file:
        file.write(speech_text)

    print(f"保存が完了しました: {output_path}")
    return True


def parse_args():
    parser = argparse.ArgumentParser(description="緯度経度から現在の天気情報を取得します。")
    parser.add_argument("--lat", type=float, default=DEFAULT_LATITUDE, help="検索する地点の緯度")
    parser.add_argument("--lon", type=float, default=DEFAULT_LONGITUDE, help="検索する地点の経度")
    parser.add_argument("--output", default="weather_speech.txt", help="読み上げ文の保存先")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        raise SystemExit("環境変数 OPENWEATHER_API_KEY を設定してください。")
    save_current_weather_speech(api_key, args.lat, args.lon, args.output)
