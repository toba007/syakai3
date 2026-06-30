from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
import random
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
import xml.etree.ElementTree as ET


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "news_cache.sqlite3"
DEFAULT_OUTPUT_FILE = BASE_DIR / "news_speech.txt"
NEWS_API_EVERYTHING_ENDPOINT = "https://newsapi.org/v2/everything"
NEWS_API_ENDPOINT = "https://newsapi.org/v2/top-headlines"
NHK_RSS_ENDPOINT = "https://www3.nhk.or.jp/rss/news/cat0.xml"
DEFAULT_STOCK_LIMIT = 15
DEFAULT_REFRESH_LIMIT = 100
DEFAULT_REFRESH_INTERVAL = 10
ARCHIVE_DOMAINS = ",".join(
    [
        "nhk.or.jp",
        "nikkei.com",
        "asahi.com",
        "mainichi.jp",
        "yomiuri.co.jp",
        "sankei.com",
        "jiji.com",
        "kyodonews.jp",
    ]
)


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    url: str = ""
    published_at: str = ""

    def normalized_key(self) -> str:
        return normalize_title(self.title).casefold()


def normalize_title(title: str) -> str:
    if not title:
        return ""
    return re.sub(r"\s+", " ", title).strip()


def open_database(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    initialize_database(connection)
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS news_stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_title TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            url TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            added_at INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS news_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.commit()


def get_state(connection: sqlite3.Connection, key: str, default: str = "") -> str:
    row = connection.execute("SELECT value FROM news_state WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return str(row["value"])


def set_state(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO news_state(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def get_queue(connection: sqlite3.Connection) -> list[str]:
    raw = get_state(connection, "show_queue_json", "")
    if not raw:
        return []
    try:
        queue = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(queue, list):
        return []
    return [normalize_title(str(title)) for title in queue if normalize_title(str(title))]


def set_queue(connection: sqlite3.Connection, queue: Sequence[str]) -> None:
    set_state(connection, "show_queue_json", json.dumps(list(queue), ensure_ascii=False))


def fetch_json(endpoint: str, params: dict[str, str], timeout: float = 10.0) -> dict:
    url = f"{endpoint}?{urlencode(params)}"
    try:
        with urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API request failed: {error.code} {message}") from error
    except URLError as error:
        raise RuntimeError(f"Network request failed: {error.reason}") from error
    return json.loads(body)


def fetch_newsapi_items(api_key: str, limit: int) -> list[NewsItem]:
    if not api_key:
        return []

    params = {
        "country": "jp",
        "pageSize": str(limit),
        "apiKey": api_key,
    }
    data = fetch_json(NEWS_API_ENDPOINT, params)
    articles = data.get("articles") or []

    items: list[NewsItem] = []
    for article in articles:
        title = normalize_title(str(article.get("title", "")))
        if not title:
            continue
        source = str((article.get("source") or {}).get("name") or "newsapi")
        items.append(
            NewsItem(
                title=title,
                source=source,
                url=str(article.get("url") or ""),
                published_at=str(article.get("publishedAt") or ""),
            )
        )
    return items


def fetch_nhk_items(limit: int) -> list[NewsItem]:
    try:
        with urlopen(NHK_RSS_ENDPOINT, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"RSS request failed: {error.code} {message}") from error
    except URLError as error:
        raise RuntimeError(f"Network request failed: {error.reason}") from error

    root = ET.fromstring(body)
    items: list[NewsItem] = []
    for item in root.findall("./channel/item"):
        title = normalize_title(item.findtext("title", default=""))
        if not title:
            continue
        items.append(
            NewsItem(
                title=title,
                source="nhk",
                url=(item.findtext("link", default="") or "").strip(),
                published_at=(item.findtext("pubDate", default="") or "").strip(),
            )
        )
        if len(items) >= limit:
            break
    return items


def fetch_newsapi_archive_items(api_key: str, target_date: date, limit: int) -> list[NewsItem]:
    if not api_key:
        return []

    params = {
        "domains": ARCHIVE_DOMAINS,
        "from": target_date.isoformat(),
        "to": target_date.isoformat(),
        "sortBy": "publishedAt",
        "pageSize": str(limit),
        "apiKey": api_key,
    }
    data = fetch_json(NEWS_API_EVERYTHING_ENDPOINT, params)
    articles = data.get("articles") or []

    items: list[NewsItem] = []
    for article in articles:
        title = normalize_title(str(article.get("title", "")))
        if not title:
            continue
        source = str((article.get("source") or {}).get("name") or "newsapi")
        items.append(
            NewsItem(
                title=title,
                source=source,
                url=str(article.get("url") or ""),
                published_at=str(article.get("publishedAt") or ""),
            )
        )
    return items


def collect_candidates(api_key: str, refresh_limit: int, include_archive: bool = False) -> list[NewsItem]:
    candidates: list[NewsItem] = []
    try:
        candidates.extend(fetch_newsapi_items(api_key, refresh_limit))
    except Exception:
        pass
    try:
        candidates.extend(fetch_nhk_items(refresh_limit))
    except Exception:
        pass
    if include_archive:
        for days_ago in (1, 2):
            target_date = date.today() - timedelta(days=days_ago)
            try:
                candidates.extend(fetch_newsapi_archive_items(api_key, target_date, refresh_limit))
            except Exception:
                pass

    seen: set[str] = set()
    deduped: list[NewsItem] = []
    for item in candidates:
        key = item.normalized_key()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def load_stock(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT id, normalized_title, title, source, url, published_at, added_at
        FROM news_stock
        ORDER BY added_at ASC, id ASC
        """
    ).fetchall()


def stock_contains(connection: sqlite3.Connection, normalized_title: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM news_stock WHERE normalized_title = ? LIMIT 1",
        (normalized_title,),
    ).fetchone()
    return row is not None


def trim_stock(connection: sqlite3.Connection, stock_limit: int = DEFAULT_STOCK_LIMIT) -> None:
    rows = connection.execute(
        """
        SELECT id
        FROM news_stock
        ORDER BY added_at ASC, id ASC
        """
    ).fetchall()
    if len(rows) <= stock_limit:
        return

    delete_count = len(rows) - stock_limit
    delete_ids = [int(row["id"]) for row in rows[:delete_count]]
    connection.executemany("DELETE FROM news_stock WHERE id = ?", [(item_id,) for item_id in delete_ids])


def add_one_new_item(
    connection: sqlite3.Connection,
    api_key: str,
    refresh_limit: int = DEFAULT_REFRESH_LIMIT,
    stock_limit: int = DEFAULT_STOCK_LIMIT,
    include_archive: bool = False,
    excluded_keys: set[str] | None = None,
) -> bool:
    candidates = collect_candidates(api_key, refresh_limit, include_archive=include_archive)
    if not candidates:
        return False

    excluded_keys = excluded_keys or set()
    now = int(time.time())
    for item in candidates:
        key = item.normalized_key()
        if not key:
            continue
        if key in excluded_keys:
            continue
        if stock_contains(connection, key):
            continue
        connection.execute(
            """
            INSERT INTO news_stock(
                normalized_title, title, source, url, published_at, added_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key, item.title, item.source, item.url, item.published_at, now),
        )
        trim_stock(connection, stock_limit)
        connection.commit()
        return True

    return False


def remove_stock_item(connection: sqlite3.Connection, normalized_title: str) -> None:
    if not normalized_title:
        return

    connection.execute(
        "DELETE FROM news_stock WHERE normalized_title = ?",
        (normalized_title,),
    )
    queue = [title for title in get_queue(connection) if title != normalized_title]
    set_queue(connection, queue)
    connection.commit()


def replace_displayed_item(
    connection: sqlite3.Connection,
    selected: sqlite3.Row | None,
    api_key: str,
    refresh_limit: int = DEFAULT_REFRESH_LIMIT,
    stock_limit: int = DEFAULT_STOCK_LIMIT,
) -> bool:
    if selected is None:
        return False

    displayed_key = str(selected["normalized_title"])
    remove_stock_item(connection, displayed_key)
    added = add_one_new_item(
        connection,
        api_key,
        refresh_limit=refresh_limit,
        stock_limit=stock_limit,
        include_archive=True,
        excluded_keys={displayed_key},
    )
    sync_queue_with_stock(connection)
    return added


def seed_stock(
    connection: sqlite3.Connection,
    api_key: str,
    refresh_limit: int = DEFAULT_REFRESH_LIMIT,
    stock_limit: int = DEFAULT_STOCK_LIMIT,
) -> int:
    count = 0
    while len(load_stock(connection)) < stock_limit:
        added = add_one_new_item(
            connection,
            api_key,
            refresh_limit=refresh_limit,
            stock_limit=stock_limit,
            include_archive=True,
        )
        if not added:
            break
        count += 1
    return count


def get_stock_title_map(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = load_stock(connection)
    return {str(row["normalized_title"]): row for row in rows}


def rebuild_queue(connection: sqlite3.Connection) -> list[str]:
    rows = load_stock(connection)
    titles = [str(row["normalized_title"]) for row in rows if str(row["normalized_title"])]
    random.shuffle(titles)
    set_queue(connection, titles)
    connection.commit()
    return titles


def sync_queue_with_stock(connection: sqlite3.Connection) -> list[str]:
    queue = get_queue(connection)
    stock_map = get_stock_title_map(connection)
    stock_titles = set(stock_map.keys())

    queue = [title for title in queue if title in stock_titles]
    queued_titles = set(queue)
    missing_titles = [title for title in stock_titles if title not in queued_titles]
    random.shuffle(missing_titles)
    queue.extend(missing_titles)
    set_queue(connection, queue)
    connection.commit()
    return queue


def select_next_item(connection: sqlite3.Connection) -> sqlite3.Row | None:
    stock_map = get_stock_title_map(connection)
    if not stock_map:
        return None

    queue = sync_queue_with_stock(connection)
    if not queue:
        queue = rebuild_queue(connection)
        if not queue:
            return None

    normalized_title = queue.pop(0)
    set_queue(connection, queue)
    connection.commit()
    return stock_map.get(normalized_title)


def get_next_display_item(
    connection: sqlite3.Connection,
    api_key: str,
    refresh_limit: int = DEFAULT_REFRESH_LIMIT,
    stock_limit: int = DEFAULT_STOCK_LIMIT,
) -> sqlite3.Row | None:
    queue = get_queue(connection)
    if not queue:
        add_one_new_item(
            connection,
            api_key,
            refresh_limit=refresh_limit,
            stock_limit=stock_limit,
            include_archive=True,
        )
        sync_queue_with_stock(connection)
        queue = get_queue(connection)
        if not queue:
            rebuild_queue(connection)
    return select_next_item(connection)


def build_speech_text(title: str) -> str:
    if not title:
        return "今のニュースです。以上、ニュースをお伝えしました。"
    return f"今のニュースです。{title}。以上、ニュースをお伝えしました。"


def write_text_file(path: str | Path, text: str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return output_path


def fetch_japan_news(
    api_key: str,
    output_file: str | Path = DEFAULT_OUTPUT_FILE,
    *,
    refresh_limit: int = DEFAULT_REFRESH_LIMIT,
    stock_limit: int = DEFAULT_STOCK_LIMIT,
    db_path: str | Path | None = None,
) -> str:
    with open_database(db_path) as connection:
        seed_stock(
            connection,
            api_key,
            refresh_limit=refresh_limit,
            stock_limit=stock_limit,
        )
        selected = get_next_display_item(
            connection,
            api_key,
            refresh_limit=refresh_limit,
            stock_limit=stock_limit,
        )
        replace_displayed_item(
            connection,
            selected,
            api_key,
            refresh_limit=refresh_limit,
            stock_limit=stock_limit,
        )

    title = str(selected["title"]) if selected is not None else ""
    speech_text = build_speech_text(title)
    write_text_file(output_file, speech_text)
    print(f"Saved output: {Path(output_file).resolve()}")
    print(speech_text)
    return title


def run_watch_loop(
    api_key: str,
    *,
    refresh_limit: int = DEFAULT_REFRESH_LIMIT,
    stock_limit: int = DEFAULT_STOCK_LIMIT,
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL,
    db_path: str | Path | None = None,
) -> int:
    while True:
        with open_database(db_path) as connection:
            add_one_new_item(
                connection,
                api_key,
                refresh_limit=refresh_limit,
                stock_limit=stock_limit,
                include_archive=True,
            )
            if not load_stock(connection):
                seed_stock(
                    connection,
                    api_key,
                    refresh_limit=refresh_limit,
                    stock_limit=stock_limit,
                )
            sync_queue_with_stock(connection)

        time.sleep(max(10, refresh_interval))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh and export Japanese news speech text.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_FILE), help="Speech output file")
    parser.add_argument("--db-path", default="", help="SQLite cache path")
    parser.add_argument("--refresh-limit", type=int, default=DEFAULT_REFRESH_LIMIT, help="Maximum fetched items per source")
    parser.add_argument("--stock-limit", type=int, default=DEFAULT_STOCK_LIMIT, help="Maximum stock size")
    parser.add_argument("--refresh-interval", type=int, default=DEFAULT_REFRESH_INTERVAL, help="Seconds between refreshes in watch mode")
    parser.add_argument("--watch", action="store_true", help="Keep refreshing and rewriting the output")
    parser.add_argument("--news-api-key", default="", help="NewsAPI key")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    api_key = args.news_api_key or ""
    if not api_key:
        import os

        api_key = os.environ.get("NEWS_API_KEY", "")

    try:
        if args.watch:
            return run_watch_loop(
                api_key,
                refresh_limit=args.refresh_limit,
                stock_limit=args.stock_limit,
                refresh_interval=args.refresh_interval,
                db_path=args.db_path or None,
            )

        fetch_japan_news(
            api_key,
            args.output,
            refresh_limit=args.refresh_limit,
            stock_limit=args.stock_limit,
            db_path=args.db_path or None,
        )
    except Exception as exc:
        write_text_file(args.output, f"ニュースを取得できませんでした。{exc}")
        print(f"News refresh failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
