from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


API_KEY = "596678fe1350853517f62a378a8b5eaa"
DEFAULT_OUTPUT_FILE = "weather_speech.txt"
GEOCODING_ENDPOINT = "https://api.openweathermap.org/geo/1.0/direct"
CURRENT_WEATHER_ENDPOINT = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_ENDPOINT = "https://api.openweathermap.org/data/2.5/forecast"
OPEN_METEO_ARCHIVE_ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"

CURRENT_WORDS = ("現在の", "今の", "現在", "いま", "今")
TODAY_WORDS = ("今日", "きょう", "本日")
YESTERDAY_WORDS = ("一昨日", "おととい", "昨日", "きのう")
TOMORROW_WORDS = ("明後日", "あさって", "明日", "あした", "あす")
TIME_WORDS = (
    *CURRENT_WORDS,
    *TODAY_WORDS,
    *YESTERDAY_WORDS,
    *TOMORROW_WORDS,
)
WEATHER_WORDS = (
    "天気予報",
    "天気",
    "予報",
    "教えて",
    "ください",
    "ちょうだい",
    "を",
    "は",
    "が",
    "の",
)

DAY_LABELS = {
    -2: "一昨日",
    -1: "昨日",
    0: "今日",
    1: "明日",
    2: "明後日",
}

OPEN_METEO_WEATHER_CODES = {
    0: "快晴",
    1: "晴れ",
    2: "一部曇り",
    3: "曇り",
    45: "霧",
    48: "霧氷を伴う霧",
    51: "弱い霧雨",
    53: "霧雨",
    55: "強い霧雨",
    56: "弱い着氷性の霧雨",
    57: "強い着氷性の霧雨",
    61: "弱い雨",
    63: "雨",
    65: "強い雨",
    66: "弱い着氷性の雨",
    67: "強い着氷性の雨",
    71: "弱い雪",
    73: "雪",
    75: "強い雪",
    77: "雪粒",
    80: "弱いにわか雨",
    81: "にわか雨",
    82: "強いにわか雨",
    85: "弱いにわか雪",
    86: "強いにわか雪",
    95: "雷雨",
    96: "ひょうを伴う雷雨",
    99: "強いひょうを伴う雷雨",
}


def get_json(endpoint, params):
    url = f"{endpoint}?{urlencode(params)}"
    try:
        with urlopen(url, timeout=10) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API request failed: {error.code} {message}") from error
    except URLError as error:
        raise RuntimeError(f"Network request failed: {error.reason}") from error

    return json.loads(body)


def detect_day_offset(text):
    if any(word in text for word in ("一昨日", "おととい")):
        return -2
    if any(word in text for word in ("昨日", "きのう")):
        return -1
    if any(word in text for word in ("明後日", "あさって")):
        return 2
    if any(word in text for word in ("明日", "あした", "あす")):
        return 1
    return 0


def detect_period(text):
    if any(word in text for word in CURRENT_WORDS):
        return "current"
    day_offset = detect_day_offset(text)
    if day_offset < 0:
        return "past"
    if day_offset > 0:
        return "future"
    return "today"


def extract_city_name(text):
    city = text.strip()
    for word in (*TIME_WORDS, *WEATHER_WORDS):
        city = city.replace(word, " ")
    city = re.sub(r"[、。,.!?！？]", " ", city)
    city = re.sub(r"\s+", " ", city).strip()
    return city or None


def parse_weather_request(text):
    return {
        "city": extract_city_name(text),
        "day_offset": detect_day_offset(text),
        "period": detect_period(text),
    }


def geocode_city(city_name, api_key=API_KEY):
    queries = [city_name, f"{city_name},JP"]

    for query in queries:
        params = {
            "q": query,
            "limit": 5,
            "appid": api_key,
        }
        candidates = get_json(GEOCODING_ENDPOINT, params)
        if not candidates:
            continue

        selected = candidates[0]
        local_names = selected.get("local_names") or {}
        display_name = local_names.get("ja") or selected.get("name") or city_name

        return {
            "name": display_name,
            "latitude": selected["lat"],
            "longitude": selected["lon"],
        }

    return None


def fetch_forecast(latitude, longitude, api_key=API_KEY):
    params = {
        "lat": latitude,
        "lon": longitude,
        "appid": api_key,
        "lang": "ja",
        "units": "metric",
    }
    return get_json(FORECAST_ENDPOINT, params)


def fetch_current_weather(latitude, longitude, api_key=API_KEY):
    params = {
        "lat": latitude,
        "lon": longitude,
        "appid": api_key,
        "lang": "ja",
        "units": "metric",
    }
    return get_json(CURRENT_WEATHER_ENDPOINT, params)


def fetch_historical_weather(latitude, longitude, day_offset):
    target_date = date.today() + timedelta(days=day_offset)
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "daily": ",".join(
            (
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
            )
        ),
        "timezone": "auto",
    }
    return get_json(OPEN_METEO_ARCHIVE_ENDPOINT, params)


def local_date_from_forecast_item(item, timezone_offset_seconds):
    forecast_time = datetime.fromtimestamp(item["dt"], timezone.utc)
    local_time = forecast_time + timedelta(seconds=timezone_offset_seconds)
    return local_time.date()


def select_daily_forecasts(forecast_data, day_offset):
    timezone_offset_seconds = forecast_data.get("city", {}).get("timezone", 0)
    now_local = datetime.now(timezone.utc) + timedelta(seconds=timezone_offset_seconds)
    target_date = (now_local + timedelta(days=day_offset)).date()

    daily_items = [
        item
        for item in forecast_data.get("list", [])
        if local_date_from_forecast_item(item, timezone_offset_seconds) == target_date
    ]
    return daily_items, target_date


def summarize_daily_forecast(city_name, daily_items, day_offset):
    if not daily_items:
        day_label = DAY_LABELS.get(day_offset, f"{day_offset}日後")
        return f"{city_name}の{day_label}の天気予報を取得できませんでした。"

    descriptions = [
        item["weather"][0]["description"]
        for item in daily_items
        if item.get("weather")
    ]
    description = Counter(descriptions).most_common(1)[0][0]

    temperatures = [item["main"]["temp"] for item in daily_items]
    min_temperature = round(min(temperatures))
    max_temperature = round(max(temperatures))
    day_label = DAY_LABELS.get(day_offset, f"{day_offset}日後")

    return (
        f"{city_name}の{day_label}の天気は{description}。"
        f"気温は{min_temperature}度から{max_temperature}度くらいです。"
    )


def summarize_current_weather(city_name, current_data):
    weather_items = current_data.get("weather") or []
    description = weather_items[0]["description"] if weather_items else "不明"
    main_data = current_data.get("main") or {}
    temperature = round(main_data.get("temp", 0))
    humidity = main_data.get("humidity")

    if humidity is None:
        return f"{city_name}の現在の天気は{description}。気温は{temperature}度です。"

    return (
        f"{city_name}の現在の天気は{description}。"
        f"気温は{temperature}度、湿度は{humidity}パーセントです。"
    )


def summarize_historical_weather(city_name, historical_data, day_offset):
    daily_data = historical_data.get("daily") or {}
    weather_codes = daily_data.get("weather_code") or []
    max_temperatures = daily_data.get("temperature_2m_max") or []
    min_temperatures = daily_data.get("temperature_2m_min") or []
    precipitation_sums = daily_data.get("precipitation_sum") or []
    day_label = DAY_LABELS.get(day_offset, f"{abs(day_offset)}日前")

    if not weather_codes:
        return f"{city_name}の{day_label}の過去天気を取得できませんでした。"

    description = OPEN_METEO_WEATHER_CODES.get(weather_codes[0], "不明")
    max_temperature = round(max_temperatures[0]) if max_temperatures else None
    min_temperature = round(min_temperatures[0]) if min_temperatures else None
    precipitation = precipitation_sums[0] if precipitation_sums else None

    temperature_text = ""
    if max_temperature is not None and min_temperature is not None:
        temperature_text = f"気温は{min_temperature}度から{max_temperature}度くらいでした。"

    precipitation_text = ""
    if precipitation is not None:
        precipitation_text = f"降水量は{precipitation}ミリでした。"

    return (
        f"{city_name}の{day_label}の天気は{description}。"
        f"{temperature_text}{precipitation_text}"
    )


def build_weather_speech(city_name, day_offset, period="today", api_key=API_KEY):
    location = geocode_city(city_name, api_key)
    if location is None:
        return None

    if period == "current":
        current_data = fetch_current_weather(
            location["latitude"],
            location["longitude"],
            api_key,
        )
        return summarize_current_weather(location["name"], current_data)

    if period == "past":
        try:
            historical_data = fetch_historical_weather(
                location["latitude"],
                location["longitude"],
                day_offset,
            )
        except RuntimeError:
            day_label = DAY_LABELS.get(day_offset, f"{abs(day_offset)}日前")
            return (
                f"{location['name']}の{day_label}の天気は取得できませんでした。"
                "Open-Meteoの過去天気APIへの接続を確認してください。"
            )
        return summarize_historical_weather(location["name"], historical_data, day_offset)

    forecast_data = fetch_forecast(
        location["latitude"],
        location["longitude"],
        api_key,
    )
    daily_items, _ = select_daily_forecasts(forecast_data, day_offset)
    if not daily_items and day_offset == 0:
        current_data = fetch_current_weather(
            location["latitude"],
            location["longitude"],
            api_key,
        )
        return summarize_current_weather(location["name"], current_data)

    return summarize_daily_forecast(location["name"], daily_items, day_offset)


def save_weather_speech(speech_text, output_file=DEFAULT_OUTPUT_FILE):
    output_path = os.path.abspath(output_file)
    with open(output_path, "w", encoding="utf-8") as file:
        file.write(speech_text)
    return output_path


def ask_weather_request(prompt="知りたい天気を入力してください: "):
    while True:
        user_input = input(prompt).strip()
        request = parse_weather_request(user_input)
        if request["city"]:
            return request
        print("都市名がわかりませんでした。例: 東京の今日の天気")


def create_weather_report_from_text(text, output_file=DEFAULT_OUTPUT_FILE, api_key=API_KEY):
    request = parse_weather_request(text)
    if not request["city"]:
        return None, "都市名がわかりませんでした。"

    speech_text = build_weather_speech(
        request["city"],
        request["day_offset"],
        request["period"],
        api_key,
    )
    if speech_text is None:
        return None, f"{request['city']} の場所が見つかりませんでした。"

    output_path = save_weather_speech(speech_text, output_file)
    return speech_text, output_path


def create_weather_report_interactive(output_file=DEFAULT_OUTPUT_FILE, api_key=API_KEY):
    while True:
        request = ask_weather_request()
        speech_text = build_weather_speech(
            request["city"],
            request["day_offset"],
            request["period"],
            api_key,
        )
        if speech_text is not None:
            output_path = save_weather_speech(speech_text, output_file)
            return speech_text, output_path
        print(f"{request['city']} の場所が見つかりませんでした。もう一度入力してください。")
