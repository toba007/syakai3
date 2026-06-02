import os
import xml.etree.ElementTree as ET

import requests


MESSAGE_FETCHING = "\u004e\u0065\u0077\u0073\u0041\u0050\u0049\u304b\u3089\u65e5\u672c\u306e\u6700\u65b0\u30cb\u30e5\u30fc\u30b9\u3092\u53d6\u5f97\u3057\u3066\u3044\u307e\u3059..."
MESSAGE_NETWORK_ERROR = "\u30cd\u30c3\u30c8\u30ef\u30fc\u30af\u30a8\u30e9\u30fc\u304c\u767a\u751f\u3057\u307e\u3057\u305f"
MESSAGE_API_ERROR = "\u0041\u0050\u0049\u30ea\u30af\u30a8\u30b9\u30c8\u306b\u5931\u6557\u3057\u307e\u3057\u305f\u3002\u30b9\u30c6\u30fc\u30bf\u30b9\u30b3\u30fc\u30c9"
MESSAGE_ERROR_DETAIL = "\u30a8\u30e9\u30fc\u5185\u5bb9"
MESSAGE_NOT_ENOUGH_NEWS = "\u30cb\u30e5\u30fc\u30b9\u30bf\u30a4\u30c8\u30eb\u304c3\u4ef6\u672a\u6e80\u306e\u305f\u3081\u3001\u30c6\u30ad\u30b9\u30c8\u3092\u4f5c\u6210\u3067\u304d\u307e\u305b\u3093\u3002"
MESSAGE_NO_NEWS = "\u30cb\u30e5\u30fc\u30b9\u30bf\u30a4\u30c8\u30eb\u3092\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002"
MESSAGE_FETCHING_RSS = "\u004e\u0065\u0077\u0073\u0041\u0050\u0049\u3067\u53d6\u5f97\u3067\u304d\u306a\u304b\u3063\u305f\u305f\u3081\u3001\u004e\u0048\u004b\u30cb\u30e5\u30fc\u30b9\u0052\u0053\u0053\u304b\u3089\u53d6\u5f97\u3057\u3066\u3044\u307e\u3059..."
MESSAGE_CREATING_TEXT = "\u97f3\u58f0\u5408\u6210\u7528\u306e\u30c6\u30ad\u30b9\u30c8\u3092\u4f5c\u6210\u3057\u3066\u3044\u307e\u3059..."
MESSAGE_SAVED = "\u4fdd\u5b58\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f"


def fetch_newsapi_titles(api_key, limit=3):
    endpoint = "https://newsapi.org/v2/top-headlines"
    params = {
        "country": "jp",
        "apiKey": api_key,
    }

    print(MESSAGE_FETCHING)

    try:
        response = requests.get(endpoint, params=params)
    except requests.exceptions.RequestException as error:
        print(f"{MESSAGE_NETWORK_ERROR}: {error}")
        return

    if response.status_code != 200:
        print(f"{MESSAGE_API_ERROR}: {response.status_code}")
        print(f"{MESSAGE_ERROR_DETAIL}: {response.text}")
        return []

    data = response.json()
    articles = data.get("articles", [])
    return [article.get("title", "").strip() for article in articles if article.get("title")][:limit]


def fetch_nhk_rss_titles(limit=3):
    endpoint = "https://www3.nhk.or.jp/rss/news/cat0.xml"

    print(MESSAGE_FETCHING_RSS)

    try:
        response = requests.get(endpoint, timeout=10)
    except requests.exceptions.RequestException as error:
        print(f"{MESSAGE_NETWORK_ERROR}: {error}")
        return []

    if response.status_code != 200:
        print(f"{MESSAGE_API_ERROR}: {response.status_code}")
        print(f"{MESSAGE_ERROR_DETAIL}: {response.text}")
        return []

    root = ET.fromstring(response.content)
    titles = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title", default="").strip()
        if title:
            titles.append(title)
        if len(titles) >= limit:
            break

    return titles


def build_speech_text(titles):
    if not titles:
        return "\u4eca\u65e5\u306e\u30cb\u30e5\u30fc\u30b9\u306f\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002"

    intro = "\u4eca\u65e5\u306e\u4e3b\u306a\u30cb\u30e5\u30fc\u30b9\u3060\u3088\u3002"
    body = "".join(
        f"{index}\u3064\u76ee\u3001{title}\u3002"
        for index, title in enumerate(titles, start=1)
    )
    outro = "\u4ee5\u4e0a\u3001\u30cb\u30e5\u30fc\u30b9\u3092\u304a\u4f1d\u3048\u3057\u307e\u3057\u305f\u3002"
    return intro + body + outro


def fetch_japan_news(api_key, output_file="news_speech.txt"):
    titles = fetch_newsapi_titles(api_key)

    if len(titles) < 3:
        titles = fetch_nhk_rss_titles()

    if not titles:
        print(MESSAGE_NO_NEWS)

    speech_text = build_speech_text(titles)

    print(MESSAGE_CREATING_TEXT)

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(speech_text)

    absolute_path = os.path.abspath(output_file)
    print(f"{MESSAGE_SAVED}: {absolute_path}")


if __name__ == "__main__":
    api_key = "0685b528fd104972aeeed4b99ec8c4f6"
    fetch_japan_news(api_key)
