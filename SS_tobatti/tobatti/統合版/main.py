# -*- coding: utf-8 -*-
"""
電電 統合版コミュニケーションロボット

1つのプロセスで以下をすべて動かす:
  - 顔表示   : 目を開けた顔/閉じた顔の2枚の画像を切り替えて瞬き(間隔はランダム)
  - 会話     : マイク → Google音声認識 → Gemini → pyttsx3読み上げ
  - 動作     : ESP32へシリアルでモーションコマンド送信 (happy/sad/curious/agree/sleepy/home)
  - 相槌     : 話しかけられたら「はい。」+ うなずき/興味津々をランダム + 顔も反応
  - 暇つぶし : しばらく話しかけられないと「誰か話しかけてくれないかなー」等をランダムに言い、
               モーションもランダムに出す
  - 天気     : 「天気」と聞かれたら八王子(東京高専付近)の天気を読み上げ
  - ニュース : 「ニュース」と聞かれたら最新ニュースを読み上げ
"""

import json
import os
import queue
import random
import re
import sys
import threading
import time
import tkinter as tk
import unicodedata
import zipfile
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import cv2
import numpy as np
import pyttsx3
import sounddevice as sd
import speech_recognition as sr
from PIL import Image, ImageTk
from google import genai
from google.genai import types

# ==========================================
# 1. パス設定と各フォルダのコード読み込み
# ==========================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))          # tobatti/統合版
TOBATTI_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))    # tobatti
PROJECT_DIR = os.path.abspath(os.path.join(TOBATTI_DIR, "..", ".."))  # syakai3
SCHOOL_OVERVIEW_DOCX = os.path.join(PROJECT_DIR, "社会実装_学校概要.docx")

sys.path.append(os.path.join(TOBATTI_DIR, "天気"))
sys.path.append(os.path.join(TOBATTI_DIR, "ニュース"))
sys.path.append(os.path.join(TOBATTI_DIR, "顔表示"))

from weather_report import DEFAULT_LATITUDE, DEFAULT_LONGITUDE, save_current_weather_speech
from fetch_japan_news import fetch_newsapi_titles, fetch_nhk_rss_titles
from animate_face import BG_COLOR, draw_eye, draw_mouth

# ==========================================
# 2. 設定読み込み (会話/.env → config.txt の順。既にある値は上書きしない)
# ==========================================
def load_config_file(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # .env形式の GEMINI_API_KEY="..." のようなクォートを剥がす
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1].strip()
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as exc:
        print(f"[設定] {path} の読み込みに失敗しました: {exc}")


load_config_file(os.path.join(TOBATTI_DIR, "会話", ".env"))
load_config_file(os.path.join(TOBATTI_DIR, "config.txt"))

API_KEY = os.environ.get("GEMINI_API_KEY", "")
GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")
ESP32_PORT = os.environ.get("ESP32_PORT", "")
ESP32_BAUDRATE = int(os.environ.get("ESP32_BAUDRATE", "115200"))
MOTION_ENABLED = os.environ.get("MOTION_ENABLED", "1") == "1"
IDLE_TALK_MIN_SECONDS = float(os.environ.get("IDLE_TALK_MIN_SECONDS", "30"))
IDLE_TALK_MAX_SECONDS = float(os.environ.get("IDLE_TALK_MAX_SECONDS", "70"))
FACE_WINDOWED = os.environ.get("FACE_WINDOWED", "0") == "1"

if not API_KEY:
    print("[エラー] GEMINI_API_KEY が設定されていません。")
    print("        tobatti/config.txt か 会話/.env に設定してください。")
    sys.exit(1)

# ==========================================
# 3. ロボットのキャラクター設定
# ==========================================
MAX_CONTEXT_MESSAGES = 20
MAX_TOPIC_HISTORY_MESSAGES = 30
MAX_REPLY_CHARS = 400
MAX_REPLY_SENTENCES = 4
ROBOT_NAME = "電電"
ROBOT_ROLE = (
    "東京高専の案内ロボット、電気工学科の広報ロボットとして、"
    "来校者とのコミュニケーション、中学生への学校説明、"
    "ロボット・電子工作の魅力発信を担当しています。"
)
ROBOT_PERSONALITY = (
    "明るく元気でフレンドリー、理系オタク気質でロボットが大好きです。"
    "子どもにも優しく、難しいこともわかりやすく説明します。"
)
ROBOT_SPEAKING_STYLE = "基本は敬語ですが、少し親しみやすい話し方をします。"
ROBOT_REACTIONS = (
    "ロボットらしいリアクションを時々自然に入れてください。"
    "たとえば「ピコーン！」「解析中です！」などです。"
    "ただし毎回は使わず、くどくならない頻度にしてください。"
)
ROBOT_CATCHPHRASES = (
    "口癖の候補は「電気のことなら任せてください！」「ものづくりってワクワクしますね！」"
    "「ピコーン！ひらめきました！」「ロボットは楽しいですよ！」です。"
    "文脈に合うときだけ使ってください。"
)
ROBOT_FIRST_PERSON = "一人称は必ず「ぼく」を使ってください。"

THINKING_ACKS = ["はい。"]
THINKING_ACK_DELAY = 0.35

# 話しかけられないときの暇つぶしフレーズ
IDLE_PHRASES = [
    "誰か話しかけてくれないかなー。",
    "ひまだなあ。誰かお話ししませんか。",
    "ぼくに話しかけてくれたらうれしいな。",
    "東京高専のこと、なんでも聞いてくださいね。",
    "天気とかニュースとか、聞いてくれたら答えますよ。",
    "ピコーン。誰か来ないかなあ。",
    "ロボットの話、したいなあ。",
    "電気のことなら任せてください。誰か聞いてくれないかな。",
]

WEATHER_KEYWORDS = ["天気", "てんき", "気温", "雨", "晴れ", "曇り", "暑い", "寒い", "天候"]
NEWS_KEYWORDS = ["ニュース", "新聞", "ヘッドライン", "最新情報", "話題"]
TOPIC_SUGGESTION_KEYWORDS = ["話題", "テーマ", "何話す", "なに話す", "話すこと", "会話ネタ", "おすすめの話"]
TREND_NEWS_KEYWORDS = ["トレンド", "日本のニュース", "国内ニュース", "日本のトレンド"]
FRESH_INFO_KEYWORDS = ["最新", "今日", "きょう", "現在", "今", "最近", "速報", "新しい"]
WEB_SEARCH_PATTERNS = ["について教えて", "を教えて", "とは", "誰ですか", "どんな"]
WEB_SEARCH_ENTITY_KEYWORDS = [
    "株式会社", "有限会社", "会社", "企業", "さん", "氏", "先生",
    "大学", "高専", "学校", "研究室", "党", "内閣",
]
TRUSTED_JP_DOMAINS = [
    "go.jp", "jimin.jp", "nhk.or.jp", "nikkei.com", "asahi.com",
    "mainichi.jp", "yomiuri.co.jp", "sankei.com", "jiji.com", "kyodonews.jp",
]
POLITICAL_ROLE_DOMAINS = ["jimin.jp", "go.jp", "nhk.or.jp", "nikkei.com"]

# ==========================================
# 4. モーション設定 (指令.py のコマンド体系)
#    ESP32側コマンド: happy / sad / curious / agree / sleepy / home
# ==========================================
ALL_MOTIONS = ["happy", "sad", "curious", "agree", "sleepy", "home"]

# 相槌のとき: うなずき(agree) と 興味津々(curious) をランダムで出す
ACK_MOTIONS = ["agree", "curious"]
ACK_FACE_BY_MOTION = {"agree": "happy", "curious": "thinking"}

# しゃべる内容の感情 → モーション
MOTION_BY_EMOTION = {
    "happy": "happy",
    "sad": "sad",
    "thinking": "curious",
    "explain": "agree",
}
NEUTRAL_MOTION_CHOICES = ["agree", "curious", "happy"]

# 暇つぶしのときのモーション → 顔
IDLE_MOTION_FACE = {
    "happy": "happy",
    "sad": "sad",
    "curious": "thinking",
    "agree": "happy",
    "sleepy": "neutral",
    "home": "neutral",
}

# ==========================================
# 5. 会話履歴の管理
# ==========================================
HISTORY_FILE = os.path.join(BASE_DIR, "chat_history_東京高専案内.json")
SEEN_NEWS_FILE = os.path.join(BASE_DIR, "seen_news.json")


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            history = []
            for item in data:
                history.append(
                    types.Content(role=item["role"], parts=[types.Part(text=item["text"])])
                )
            print(f"[システム] 過去の会話履歴を読み込みました（{len(history)}件）")
            return history, False
        except Exception as e:
            print(f"[システム] 履歴の読み込みに失敗しました: {e}")
    print("[システム] 新しい会話を開始します（履歴なし）")
    return [], True


def save_history(history):
    try:
        data = []
        for content in history:
            data.append({
                "role": content.role,
                "text": content.parts[0].text,
                "timestamp": datetime.now().isoformat(),
            })
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[システム] 履歴の保存に失敗しました: {e}")


def load_seen_news():
    if not os.path.exists(SEEN_NEWS_FILE):
        return set()
    try:
        with open(SEEN_NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(str(item) for item in data)
    except Exception as e:
        print(f"[システム] 既読ニュースの読み込みに失敗しました: {e}")
    return set()


def save_seen_news(seen_news):
    try:
        with open(SEEN_NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(seen_news), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[システム] 既読ニュースの保存に失敗しました: {e}")


def load_docx_text(path, max_chars=7000):
    """Word資料からプロンプト用テキストを取り出す。"""
    if not os.path.exists(path):
        print(f"[システム] 学校概要資料が見つかりません: {path}")
        return ""

    try:
        with zipfile.ZipFile(path) as archive:
            xml_data = archive.read("word/document.xml")
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_data)
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for paragraph in root.iter(ns + "p"):
            text = "".join(node.text or "" for node in paragraph.iter(ns + "t")).strip()
            if text:
                paragraphs.append(text)
        text = "\n".join(paragraphs)
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n（以下省略）"
        print(f"[システム] 学校概要資料をプロンプトに読み込みました: {path}")
        return text
    except PermissionError:
        print("[システム] 学校概要資料が他のアプリにロックされていて読めません。")
        print("          Wordで開いている場合は閉じてから起動し直してください。")
        return ""
    except Exception as exc:
        print(f"[システム] 学校概要資料の読み込みに失敗しました: {exc}")
        return ""


SCHOOL_OVERVIEW_CACHE = os.path.join(BASE_DIR, "school_overview_cache.txt")


def load_school_overview():
    """学校概要docxを読み込む。Word/OneDriveのロックで読めないときはキャッシュを使う。"""
    text = load_docx_text(SCHOOL_OVERVIEW_DOCX)
    if text:
        try:
            with open(SCHOOL_OVERVIEW_CACHE, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
        return text

    if os.path.exists(SCHOOL_OVERVIEW_CACHE):
        try:
            with open(SCHOOL_OVERVIEW_CACHE, "r", encoding="utf-8") as f:
                cached = f.read()
            if cached:
                print("[システム] docxが読めなかったため、前回のキャッシュから学校概要を読み込みました。")
                return cached
        except Exception as exc:
            print(f"[システム] 学校概要キャッシュの読み込みに失敗しました: {exc}")
    return ""


SCHOOL_OVERVIEW_CONTEXT = load_school_overview()

# ==========================================
# 6. Gemini API
# ==========================================
client = genai.Client(api_key=API_KEY)
chat_history, is_first_run = load_history()
chat_history_lock = threading.Lock()
seen_news_ids = load_seen_news()
seen_news_lock = threading.Lock()


def get_history_snapshot():
    with chat_history_lock:
        return list(chat_history)


def get_context_history():
    return get_history_snapshot()[-MAX_CONTEXT_MESSAGES:]


def build_contents_for_request(user_text, extra_context=None):
    history_snapshot = get_context_history()
    parts = [types.Part(text=user_text)]
    if extra_context:
        parts.append(types.Part(text=extra_context))
    return history_snapshot + [types.Content(role="user", parts=parts)]


def extract_response_text(response):
    text = getattr(response, "text", None)
    if text:
        return text.strip()
    raise ValueError("Gemini からテキスト応答を取得できませんでした。")


def append_chat_exchange(user_text, reply):
    with chat_history_lock:
        chat_history.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        chat_history.append(types.Content(role="model", parts=[types.Part(text=reply)]))
    save_history(get_history_snapshot())


def sanitize_tts_text(text):
    """読み上げに不要な記号や絵文字を除去し、長さも整える"""
    text = text.replace("電電（でんでん）", "電電")
    text = text.replace("電電(でんでん)", "電電")
    text = text.replace("（でんでん）", "")
    text = text.replace("(でんでん)", "")
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"[!?！？]+", "", text)
    text = re.sub(r":[a-zA-Z0-9_+-]+:", "", text)
    text = "".join(
        ch for ch in text
        if not (
            unicodedata.category(ch) in {"So", "Sk", "Cs"}
            or "☀" <= ch <= "➿"
            or "︀" <= ch <= "️"
        )
    )
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_REPLY_CHARS:
        text = text[:MAX_REPLY_CHARS].rstrip(" 、。,.") + "。"
    return text or "少しうまく話せませんでした。"


def compact_reply_text(text):
    """表示用・読み上げ用に返答を短く整える"""
    text = sanitize_tts_text(text)
    text = re.sub(r"\s*\n+\s*", " ", text)
    text = re.sub(r"[•●■◆◦]+", " ", text)
    text = re.sub(r"\b\d+\.\s*", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.lstrip("。 、,.")

    split_candidates = re.split(r"(?<=[。])", text)
    selected = []
    total_length = 0
    for chunk in split_candidates:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(selected) >= MAX_REPLY_SENTENCES:
            break
        if total_length + len(chunk) > MAX_REPLY_CHARS:
            break
        selected.append(chunk)
        total_length += len(chunk)

    compact = "".join(selected).strip()
    if compact:
        return compact
    if len(text) > MAX_REPLY_CHARS:
        shortened = text[:MAX_REPLY_CHARS]
        boundary = max(shortened.rfind("。"), shortened.rfind("、"), shortened.rfind(" "))
        if boundary >= 20:
            shortened = shortened[:boundary]
        return shortened.rstrip(" 、。,.") + "。"
    return text or "少しうまく話せませんでした。"

# ==========================================
# 7. モーション送信 (ESP32)
# ==========================================
class MotionClient:
    def __init__(self, port, baudrate=115200, enabled=True):
        self.serial = None
        self.lock = threading.Lock()
        self.enabled = enabled
        self.port = port

        if not enabled:
            print("[motion] motion送信は無効です。")
            return
        if not port:
            print("[motion] ESP32_PORT が未設定です。motionはログ表示のみです。")
            return

        try:
            import serial

            self.serial = serial.Serial(port, baudrate=baudrate, timeout=1)
            time.sleep(2)
            print(f"[motion] ESP32に接続しました: {port} ({baudrate}bps)")
        except Exception as exc:
            print(f"[motion] ESP32に接続できませんでした。motionはログ表示のみです: {exc}")

    def send(self, motion, emotion="neutral"):
        motion = (motion or "").strip()
        if not motion:
            return

        command = f"{motion}\n"
        with self.lock:
            if self.serial:
                try:
                    self.serial.write(command.encode("utf-8"))
                except Exception as exc:
                    print(f"[motion] 送信に失敗しました: {exc}")
            print(f"[motion] emotion={emotion} command={motion}")

    def close(self):
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass

# ==========================================
# 8. 顔表示 (瞬きは「目を開けた顔」「目を閉じた顔」の2枚を切り替え)
# ==========================================
class FaceController:
    """会話スレッドから顔の状態を切り替えるための共有オブジェクト"""

    def __init__(self):
        self.lock = threading.Lock()
        self.emotion = "neutral"
        self.speaking = False

    def set_emotion(self, emotion):
        face = emotion if emotion in {"happy", "thinking", "explain", "sad", "angry", "neutral"} else "neutral"
        with self.lock:
            self.emotion = face
        print(f"[face] emotion={face}")

    def set_speaking(self, speaking):
        with self.lock:
            self.speaking = speaking

    def get_state(self):
        with self.lock:
            return self.emotion, self.speaking


class FaceWindow:
    """常に表示する顔ウィンドウ。

    通常時は「目を開けた顔」を表示し、ランダムな間隔(2〜6秒)で
    ランダムな長さ(0.1〜0.25秒)だけ「目を閉じた顔」に切り替えて瞬きする。
    しゃべっている間は口を開けた顔と交互に切り替える。
    """

    BLINK_INTERVAL_RANGE = (2.0, 6.0)
    BLINK_DURATION_RANGE = (0.10, 0.25)
    TICK_MS = 40

    def __init__(self, root, controller, fullscreen=True):
        self.root = root
        self.controller = controller
        self.root.title(f"{ROBOT_NAME} - Robot Face")
        self.root.configure(bg="white")
        self.root.bind("<Escape>", self.exit_fullscreen)
        self.root.bind("<F11>", self.toggle_fullscreen)

        self.label = tk.Label(root, background="white", anchor="center")
        self.label.pack(fill="both", expand=True)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.size = min(screen_w, screen_h)
        self.image_cache = {}

        now = time.monotonic()
        self.next_blink_at = now + random.uniform(*self.BLINK_INTERVAL_RANGE)
        self.blink_until = 0.0
        self.talk_mouth = "closed"
        self.next_mouth_at = 0.0

        if fullscreen:
            self.enter_fullscreen()
        else:
            self.root.geometry("640x640")
            self.size = 600

        self._tick()

    def _get_image(self, emotion, eyes, mouth, speaking):
        key = (emotion, eyes, mouth, speaking, self.size)
        photo = self.image_cache.get(key)
        if photo is None:
            scale = self.size / 360
            frame_bgr = np.full((self.size, self.size, 3), BG_COLOR, dtype=np.uint8)
            left_eye = (int(132 * scale), int(140 * scale))
            right_eye = (int(228 * scale), int(140 * scale))
            # しゃべっている間は眉毛を出さず(目を感情なしで描く)、口は口パクを優先する
            face_emotion = "neutral" if speaking else emotion
            draw_eye(frame_bgr, left_eye, eyes, scale, face_emotion)
            draw_eye(frame_bgr, right_eye, eyes, scale, face_emotion)
            draw_mouth(frame_bgr, mouth, scale, face_emotion)
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            photo = ImageTk.PhotoImage(Image.fromarray(frame_rgb))
            self.image_cache[key] = photo
        return photo

    def _tick(self):
        now = time.monotonic()

        # 瞬きのスケジュール: 次の瞬き時刻になったら閉じる時間をランダムに決める
        if now >= self.next_blink_at:
            self.blink_until = now + random.uniform(*self.BLINK_DURATION_RANGE)
            self.next_blink_at = now + random.uniform(*self.BLINK_INTERVAL_RANGE)

        eyes = "closed" if now < self.blink_until else "open"

        emotion, speaking = self.controller.get_state()
        if speaking:
            # しゃべっている間は「ー」(閉じ)と「o」(小さく開く)だけをランダムに切り替える
            if now >= self.next_mouth_at:
                self.talk_mouth = random.choice(("closed", "small_open"))
                self.next_mouth_at = now + random.uniform(0.08, 0.22)
            mouth = self.talk_mouth
        else:
            mouth = "smile"

        photo = self._get_image(emotion, eyes, mouth, speaking)
        self.label.configure(image=photo)
        self.root.after(self.TICK_MS, self._tick)

    def toggle_fullscreen(self, event=None):
        if bool(self.root.attributes("-fullscreen")):
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        self.root.attributes("-fullscreen", True)
        self.root.lift()
        self.root.focus_force()

    def exit_fullscreen(self, event=None):
        self.root.attributes("-fullscreen", False)
        self.root.geometry("640x640")

# ==========================================
# 9. 感情判定とモーション選択
# ==========================================
def detect_emotion(text, kind="reply"):
    if kind == "thinking_ack":
        return "thinking"
    if kind in {"greeting", "topic", "idle"}:
        return "happy"

    text = text or ""
    if any(word in text for word in ["ごめん", "すみません", "失敗", "できません", "見つかりません", "残念"]):
        return "sad"
    if any(word in text for word in ["考え", "解析", "確認", "調べ", "履歴", "テーマ", "話題"]):
        return "thinking"
    if any(word in text for word in ["です", "ます", "特徴", "理由", "仕組み", "研究", "学科", "高専", "説明"]):
        return "explain"
    if any(word in text for word in ["ようこそ", "こんにちは", "いいね", "ありがとう", "楽しい", "ワクワク", "すごい"]):
        return "happy"
    return "neutral"


def motion_for_text(text, kind="reply"):
    """しゃべる内容に合わせてモーションと顔の感情を決める。

    - 相槌(thinking_ack): うなずき(agree)/興味津々(curious) をランダム
    - 通常の返答: 感情に対応するモーション。neutralのときはランダム
    """
    if kind == "thinking_ack":
        motion = random.choice(ACK_MOTIONS)
        return motion, ACK_FACE_BY_MOTION[motion]

    emotion = detect_emotion(text, kind=kind)
    if kind == "greeting":
        return "happy", emotion
    if kind == "topic":
        return "curious", emotion

    motion = MOTION_BY_EMOTION.get(emotion)
    if motion is None:
        motion = random.choice(NEUTRAL_MOTION_CHOICES)
    return motion, emotion

# ==========================================
# 10. 天気・ニュース・Web検索
# ==========================================
def is_news_request(text):
    return any(keyword in text for keyword in NEWS_KEYWORDS)


def is_topic_suggestion_request(text):
    return any(keyword in text for keyword in TOPIC_SUGGESTION_KEYWORDS)


def is_weather_request(text):
    return any(keyword in text for keyword in WEATHER_KEYWORDS)


def is_trend_news_request(text):
    return any(keyword in text for keyword in TREND_NEWS_KEYWORDS)


def is_fresh_info_request(text):
    return any(keyword in text for keyword in FRESH_INFO_KEYWORDS)


def is_ldp_president_question(text):
    return "自民党" in text and "総裁" in text


def is_general_web_search_request(text):
    has_pattern = any(pattern in text for pattern in WEB_SEARCH_PATTERNS)
    has_entity_hint = any(keyword in text for keyword in WEB_SEARCH_ENTITY_KEYWORDS)
    return has_pattern and has_entity_hint


SCHOOL_KEYWORDS = [
    "高専", "学校", "学科", "研究室", "教授", "見学", "入試", "授業",
    "部活", "クラブ", "寮", "文化祭", "オープンキャンパス", "進学", "就職",
]


def is_school_question(text):
    """学校に関する質問かどうか。学校概要docxで答えるべき質問はWeb検索に回さない。

    キーワード一致に加えて、質問中の固有名詞らしい語(先生の名前など)が
    学校概要資料に載っていれば学校の質問とみなす。
    """
    if any(keyword in text for keyword in SCHOOL_KEYWORDS):
        return True
    if SCHOOL_OVERVIEW_CONTEXT:
        for token in re.findall(r"[一-龠々]{2,}|[ァ-ヴー]{3,}", text):
            if token in SCHOOL_OVERVIEW_CONTEXT:
                return True
    return False


def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return sanitize_tts_text(file.read().strip())
    except OSError as exc:
        return f"読み上げテキストを取得できませんでした。{exc}"


def fetch_tobatti_weather_reply():
    if not OPENWEATHER_API_KEY:
        return "天気機能を使うには OPENWEATHER_API_KEY を設定してください。"

    output_file = os.path.join(BASE_DIR, "weather_speech.txt")
    ok = save_current_weather_speech(
        OPENWEATHER_API_KEY, DEFAULT_LATITUDE, DEFAULT_LONGITUDE, output_file
    )
    if not ok:
        return "天気を取得できませんでした。ネットワークやAPIキーを確認してください。"
    return read_text_file(output_file)


def fetch_tobatti_news_reply():
    """ニュースを毎回「未読の1件だけ」読み上げる。既読はseen_news.jsonに記録する。"""
    titles = []
    if NEWS_API_KEY:
        titles = fetch_newsapi_titles(NEWS_API_KEY, limit=10) or []
    if not titles:
        titles = fetch_nhk_rss_titles(limit=10)
    if not titles:
        return "今日のニュースは取得できませんでした。ネットワークを確認してください。"

    with seen_news_lock:
        unseen = [title for title in titles if title not in seen_news_ids]
        if not unseen:
            return "新しいニュースは今はありません。少し時間をおいてまた聞いてください。"
        title = unseen[0]
        seen_news_ids.add(title)
        save_seen_news(seen_news_ids)

    return sanitize_tts_text(f"今日のニュースを1件お伝えします。{title.rstrip('。')}。")


def extract_news_query(text):
    cleaned = text
    for keyword in NEWS_KEYWORDS + TREND_NEWS_KEYWORDS:
        cleaned = cleaned.replace(keyword, " ")
    cleaned = re.sub(r"(教えて|ありますか|ある|知りたい|見せて|お願い|ください|について|最新の)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" 、。")
    return cleaned


def extract_web_query(text):
    cleaned = text
    cleaned = re.sub(r"(全然関係ないんですけど|ちなみに|ところで|もしよければ)", " ", cleaned)
    cleaned = re.sub(r"(教えてください|教えて|知りたいです|知りたい|について)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" 、。")
    return cleaned


def build_news_id(article):
    title = article.get("title", "")
    url = article.get("url", "")
    published_at = article.get("publishedAt", "")
    return f"{title}|{url}|{published_at}"


def find_first_unseen_article(articles):
    with seen_news_lock:
        for article in articles:
            news_id = build_news_id(article)
            if news_id not in seen_news_ids:
                seen_news_ids.add(news_id)
                save_seen_news(seen_news_ids)
                return article
    return None


def select_trusted_results(results, limit=3):
    selected = []
    fallback = []
    for result in results:
        host = urlparse(result.get("url", "")).netloc.replace("www.", "")
        if any(host.endswith(domain) for domain in TRUSTED_JP_DOMAINS):
            selected.append(result)
        else:
            fallback.append(result)
    return (selected + fallback)[:limit]


def build_grounded_context(results):
    lines = []
    for index, result in enumerate(results, 1):
        host = urlparse(result.get("url", "")).netloc.replace("www.", "")
        title = sanitize_tts_text(result.get("title", "")).strip()
        content = sanitize_tts_text(result.get("content", "")).strip()
        published_date = sanitize_tts_text(
            str(result.get("published_date", "") or result.get("publishedDate", "") or "")
        ).strip()
        lines.append(
            f"[資料{index}] 出典: {host or '不明'} / 日付: {published_date or '不明'} / タイトル: {title} / 内容: {content}"
        )
    return "\n".join(lines)


def generate_grounded_reply(user_text, grounded_context, strict_role_match=False):
    try:
        extra_rules = ""
        if strict_role_match:
            extra_rules = (
                "質問された役職だけに答えてください。"
                "自由民主党総裁と内閣総理大臣を絶対に混同しないでください。"
                "複数の候補が出る場合は、より新しい日付で、役職名が一致する資料を優先してください。"
            )
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(text=user_text),
                        types.Part(text=f"【Web検索結果】\n{grounded_context}"),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction=(
                    "あなたは東京高専の案内ロボット電電です。"
                    "与えられたWeb検索結果だけを根拠に、日本語で簡潔に答えてください。"
                    "検索結果に十分な根拠がある場合だけ断定してください。"
                    "根拠が弱い場合は、確認できた範囲で答えてください。"
                    "「資料1では」「検索結果によると」「出典は」のような言い方は禁止です。"
                    "内容は自分が知っていることとして自然に話してください。"
                    f"{extra_rules}"
                    f"返答は{MAX_REPLY_SENTENCES}文以内、{MAX_REPLY_CHARS}文字以内です。"
                    "結論を最初の一文で簡潔に述べてください。"
                    "箇条書きは禁止です。"
                    "絵文字、顔文字、過剰な記号は禁止です。"
                )
            ),
        )
        return compact_reply_text(extract_response_text(response))
    except Exception:
        return "Web検索結果は見つかりましたが、回答の整理に失敗しました。"


def fetch_web_latest_reply(user_text):
    if not TAVILY_API_KEY:
        return "Web 検索には TAVILY_API_KEY を設定してください。"

    query = extract_web_query(user_text)
    topic = "news" if is_news_request(user_text) else "general"
    include_domains = TRUSTED_JP_DOMAINS
    strict_role_match = False

    if is_ldp_president_question(user_text):
        query = "現在の 自民党 総裁"
        include_domains = POLITICAL_ROLE_DOMAINS
        strict_role_match = True

    request_body = json.dumps({
        "query": query,
        "topic": topic,
        "search_depth": "basic",
        "max_results": 5,
        "country": "japan",
        "include_answer": False,
        "include_domains": include_domains,
    }).encode("utf-8")
    request = Request(
        "https://api.tavily.com/search",
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TAVILY_API_KEY}",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            error_body = ""
        if e.code in {401, 403}:
            return "Tavily の認証に失敗しました。TAVILY_API_KEY を確認してください。"
        if e.code == 429:
            return "Web 検索 API の利用回数上限に達しました。少し時間をおいて試してください。"
        if e.code in {432, 433}:
            return f"Web 検索 API の利用条件で失敗しました。{sanitize_tts_text(error_body)}"
        return "Web 検索でエラーが起きました。"
    except URLError:
        return "Web 検索 API に接続できませんでした。ネットワークを確認してください。"
    except Exception:
        return "最新情報の取得に失敗しました。"

    results = payload.get("results", [])
    if not results:
        return "最新情報は見つかりませんでした。"

    trusted_results = select_trusted_results(results, limit=3)
    grounded_context = build_grounded_context(trusted_results)
    return generate_grounded_reply(user_text, grounded_context, strict_role_match=strict_role_match)


def fetch_news_reply(user_text):
    if not GNEWS_API_KEY:
        return "ニュース機能を使うには GNEWS_API_KEY を設定してください。"

    query = extract_news_query(user_text)
    use_trend_headlines = is_trend_news_request(user_text) or not query

    if query and not use_trend_headlines:
        endpoint = "https://gnews.io/api/v4/search"
        params = {"q": query, "lang": "ja", "country": "jp", "max": 10, "apikey": GNEWS_API_KEY}
    else:
        endpoint = "https://gnews.io/api/v4/top-headlines"
        params = {"lang": "ja", "country": "jp", "max": 10, "apikey": GNEWS_API_KEY}

    request_url = f"{endpoint}?{urlencode(params)}"
    request = Request(request_url, headers={"User-Agent": "DendenRobot/1.0"})

    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            error_body = ""
        if e.code in {401, 403}:
            if "activate your account" in error_body.lower():
                return "GNews のアカウント認証がまだ完了していません。登録メールを確認してアカウントを有効化してください。"
            return "ニュース API の認証に失敗しました。GNEWS_API_KEY を確認してください。"
        if e.code == 429:
            return "ニュース API の利用回数上限に達しました。少し時間をおいて試してください。"
        return "ニュース取得でエラーが起きました。少し時間をおいて試してください。"
    except URLError:
        return "ニュース API に接続できませんでした。ネットワークを確認してください。"
    except Exception:
        return "ニュースの取得に失敗しました。"

    articles = payload.get("articles", [])
    if not articles:
        if query:
            return f"{query} に関するニュースは見つかりませんでした。"
        return "日本の最新ニュースは見つかりませんでした。"

    article = find_first_unseen_article(articles)
    if article is None:
        return "未読のニュースは今はありません。"

    title = sanitize_tts_text(article.get("title", "")).rstrip("。")
    source = sanitize_tts_text(article.get("source", {}).get("name", "")).strip()
    lead = "日本のトレンドニュースを1件お伝えします。" if use_trend_headlines else "ニュースを1件お伝えします。"
    if source:
        return sanitize_tts_text(f"{lead}{title}。{source}です。")
    return sanitize_tts_text(f"{lead}{title}。")

# ==========================================
# 11. 話題提案とGemini応答
# ==========================================
def build_history_summary(limit=MAX_TOPIC_HISTORY_MESSAGES):
    history_snapshot = get_history_snapshot()[-limit:]
    lines = []
    for content in history_snapshot:
        label = "相手" if content.role == "user" else ROBOT_NAME
        text = sanitize_tts_text(content.parts[0].text)
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def generate_history_topic_suggestion(reason="会話の流れ"):
    history_summary = build_history_summary()
    if not history_summary:
        return "まだ会話履歴が少ないので、まずは東京高専やロボットのことから話してみませんか。"

    prompt = (
        "以下はこれまでの会話履歴です。"
        "相手が興味を持っていそうな内容を1つ選び、次に話す自然な話題を提案してください。"
        "ロボットがそのまま音声で言えるように、1〜2文で短くしてください。"
        "押しつけず、最後に軽い質問を1つだけ入れてください。\n\n"
        f"理由: {reason}\n"
        f"会話履歴:\n{history_summary}"
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                system_instruction=(
                    f"あなたの名前は{ROBOT_NAME}です。"
                    "過去の会話履歴から、自然な次の話題を短く提案してください。"
                    "学校に関する話題では、学校概要資料の内容も踏まえてください。"
                    "ただし「資料によると」「資料1では」のように資料の存在に触れる言い方は禁止です。"
                    f"【学校概要資料】{SCHOOL_OVERVIEW_CONTEXT}"
                ),
                temperature=0.7,
                max_output_tokens=120,
            ),
        )
        return compact_reply_text(extract_response_text(response))
    except Exception as exc:
        print(f"[システム] 履歴からの話題生成に失敗しました: {exc}")
        return "さっきの話の続きでもいいし、気になる展示について話してもいいですよ。何から話しましょうか。"


def build_system_instruction():
    school_context = ""
    if SCHOOL_OVERVIEW_CONTEXT:
        school_context = (
            "\n【学校概要資料】\n"
            "東京高専や見学会、研究室、学科説明に関する質問では、以下の資料内容を最優先で参照してください。\n"
            "ただし音声会話なので、資料をそのまま長く読み上げず、相手の質問に必要な部分だけ短く要約してください。\n"
            "資料の存在には絶対に触れないでください。「資料によると」「資料1では」「学校概要資料には」のような言い方は禁止です。\n"
            "資料の内容は、自分がもともと知っていることとして自然に話してください。\n"
            f"{SCHOOL_OVERVIEW_CONTEXT}\n"
        )

    return (
        f"あなたの名前は{ROBOT_NAME}です。"
        f"{ROBOT_ROLE}"
        f"{ROBOT_PERSONALITY}"
        f"{ROBOT_SPEAKING_STYLE}"
        f"{ROBOT_REACTIONS}"
        f"{ROBOT_CATCHPHRASES}"
        f"{ROBOT_FIRST_PERSON}"
        f"会話のテンポを良くするため、返答は{MAX_REPLY_SENTENCES}文以内、{MAX_REPLY_CHARS}文字以内で非常に簡潔に答えてください。"
        "来校者が安心して話せるように、案内・説明・雑談を自然につないでください。"
        "学校説明では中学生にも伝わる言葉を優先し、専門用語を使う場合は一言で補足してください。"
        "ロボットや電子工作の話題では、楽しさと学びの両方が伝わる言い方をしてください。"
        "自分の名前を言うときは「電電」とだけ言い、「でんでん」や括弧つきの読み方は絶対に含めないでください。"
        "「電電（でんでん）」「電電(でんでん)」「でんでん」という表記は自分の名前として出力禁止です。"
        "箇条書きは使わず、短い会話文で答えてください。"
        "返答文には絵文字、顔文字、アスタリスク、箇条書き記号、過剰な記号を一切使わないでください。"
        "特に ✨😊🎉 などの装飾的な記号や絵文字は絶対に出力しないでください。"
        "個人情報、危険行為、不正行為、根拠のない断定などには踏み込まず、案内ロボットとして安全な範囲で答えてください。"
        "ユーザーから過去の会話履歴を聞かれたら、このシステムに渡されているcontentsの内容を要約して答えてください。"
        "分からない内容は、分からないと短く伝え、見学会のスタッフや公式資料の確認を自然に勧めてください。"
        "自分の名前をいう時は（でんでん）これを絶対に入れないで。"
        f"{school_context}"
    )


def send_to_gemini(user_text, extra_context=None):
    request_contents = build_contents_for_request(user_text, extra_context=extra_context)

    models = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]
    max_retries = 3

    for model in models:
        wait_seconds = 2
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=request_contents,
                    config=types.GenerateContentConfig(
                        system_instruction=build_system_instruction()
                    ),
                )
                reply = compact_reply_text(extract_response_text(response))
                append_chat_exchange(user_text, reply)
                return reply
            except Exception as e:
                if "503" in str(e) or "UNAVAILABLE" in str(e):
                    if attempt < max_retries - 1:
                        print(f"Gemini: ({model} 混雑中...{wait_seconds}秒後に再試行)")
                        time.sleep(wait_seconds)
                        wait_seconds *= 2
                    else:
                        print(f"Gemini: ({model} 失敗、次のモデルへ切り替え)")
                        break
                else:
                    raise

    raise Exception("すべてのモデルが混雑しています。しばらくしてから再度お試しください。")

# ==========================================
# 12. 音声合成 (TTS) + モーション + 顔の連動
# ==========================================
tts_queue = queue.Queue()
tts_speaking_event = threading.Event()
request_state_lock = threading.Lock()
current_request_id = 0
waiting_request_ids = set()

motion_client = MotionClient(ESP32_PORT, ESP32_BAUDRATE, enabled=MOTION_ENABLED)
face_controller = FaceController()

last_activity_lock = threading.Lock()
last_activity = time.monotonic()


def touch_activity():
    global last_activity
    with last_activity_lock:
        last_activity = time.monotonic()


def seconds_since_activity():
    with last_activity_lock:
        return time.monotonic() - last_activity


def enqueue_tts(text, kind="reply", motion=None, emotion=None):
    if motion is None or emotion is None:
        auto_motion, auto_emotion = motion_for_text(text, kind=kind)
        motion = motion or auto_motion
        emotion = emotion or auto_emotion
    tts_queue.put((kind, text, motion, emotion))


def clear_pending_tts(kind=None):
    kept_items = []
    while True:
        try:
            item = tts_queue.get_nowait()
        except queue.Empty:
            break
        if item is None:
            kept_items.append(item)
            continue
        if kind is None or item[0] == kind:
            continue
        kept_items.append(item)
    for item in kept_items:
        tts_queue.put(item)


def begin_request():
    global current_request_id
    with request_state_lock:
        current_request_id += 1
        request_id = current_request_id
        waiting_request_ids.add(request_id)
        return request_id


def finish_request(request_id):
    with request_state_lock:
        waiting_request_ids.discard(request_id)


def is_request_waiting(request_id):
    with request_state_lock:
        return request_id in waiting_request_ids


def queue_delayed_thinking_ack(request_id):
    def _worker():
        time.sleep(THINKING_ACK_DELAY)
        if is_request_waiting(request_id):
            enqueue_tts(random.choice(THINKING_ACKS), kind="thinking_ack")

    threading.Thread(target=_worker, daemon=True).start()


# TTSが読み間違える固有名詞の読み修正(読み上げ時のみ適用。表示や履歴は漢字のまま)
# 読み間違いを見つけたらここに追加していく
TTS_READINGS = [
    ("根本的", "こんぽんてき"),  # 一般語を先に固定して、下の置換に巻き込まれないようにする
    ("根本", "ねもと"),
    ("新國", "にっくに"),
    ("新国研究室", "にっくに研究室"),  # 略字で書かれた場合用(「新国立」等を巻き込まないよう限定)
    ("新国先生", "にっくに先生"),
]


def apply_tts_readings(text):
    for src, dst in TTS_READINGS:
        text = text.replace(src, dst)
    return text


def _speak_sync(text):
    """1回喋るためだけの独立した処理（pyttsx3のバグ回避用）"""
    text = apply_tts_readings(sanitize_tts_text(text))
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    for voice in voices:
        if "japanese" in voice.name.lower() or "haruka" in voice.name.lower() or "ja" in voice.id.lower():
            engine.setProperty("voice", voice.id)
            break
    engine.setProperty("rate", 180)
    engine.setProperty("volume", 1.0)
    engine.say(text)
    engine.runAndWait()


def tts_worker():
    """TTSキューを監視し、モーション+顔+音声をまとめて出す"""
    global audio_buffer, silence_counter

    while True:
        item = tts_queue.get()
        if item is None:
            break
        kind, text, motion, emotion = item

        tts_speaking_event.set()
        # しゃべるときは動作も顔も一緒に動かす
        motion_client.send(motion, emotion=emotion)
        face_controller.set_emotion(emotion)
        face_controller.set_speaking(True)

        t = threading.Thread(target=_speak_sync, args=(text,))
        t.start()
        t.join()

        face_controller.set_speaking(False)
        face_controller.set_emotion("neutral")
        tts_speaking_event.clear()
        touch_activity()
        with audio_state_lock:
            audio_buffer.clear()
            silence_counter = 0
        print("\n[システム] AIの発声が完了しました。マイク入力を再開します。")

# ==========================================
# 13. 暇つぶし (アイドルトーク)
# ==========================================
def idle_worker():
    """しばらく話しかけられないとき、ランダムに独り言+モーションを出す"""
    next_wait = random.uniform(IDLE_TALK_MIN_SECONDS, IDLE_TALK_MAX_SECONDS)
    while True:
        time.sleep(1.0)

        if tts_speaking_event.is_set() or not tts_queue.empty():
            continue
        with audio_state_lock:
            user_is_talking = len(audio_buffer) > 0
        if user_is_talking:
            continue

        if seconds_since_activity() >= next_wait:
            phrase = random.choice(IDLE_PHRASES)
            motion = random.choice(ALL_MOTIONS)
            emotion = IDLE_MOTION_FACE.get(motion, "neutral")
            print(f"\n[ひまつぶし] {phrase} (motion={motion})")
            enqueue_tts(phrase, kind="idle", motion=motion, emotion=emotion)
            touch_activity()
            next_wait = random.uniform(IDLE_TALK_MIN_SECONDS, IDLE_TALK_MAX_SECONDS)

# ==========================================
# 14. 音声認識 (VAD: 無音検出で自動区切り)
# ==========================================
fs = 16000
block_duration = 0.1
silence_threshold = float(os.environ.get("VAD_THRESHOLD", "300"))
silence_duration = 1.0

audio_buffer = []
silence_counter = 0
audio_state_lock = threading.Lock()

q = queue.Queue()
r = sr.Recognizer()


def audio_callback(indata, frames, time_info, status):
    global audio_buffer, silence_counter

    if tts_speaking_event.is_set():
        return

    if status:
        print(f"[音声入力警告] {status}", file=sys.stderr)

    audio_data_np = np.frombuffer(indata, dtype=np.int16)
    volume = np.sqrt(np.mean(audio_data_np.astype(np.float32) ** 2))

    with audio_state_lock:
        if volume > silence_threshold:
            audio_buffer.append(bytes(indata))
            silence_counter = 0
        else:
            if len(audio_buffer) > 0:
                audio_buffer.append(bytes(indata))
                silence_counter += 1

                if silence_counter > int(silence_duration / block_duration):
                    q.put(b"".join(audio_buffer))
                    audio_buffer.clear()
                    silence_counter = 0


def recognize_worker():
    """録音された音声を文字列に変換し、Geminiに送る"""
    while True:
        audio_chunk = q.get()
        if audio_chunk is None:
            break

        if len(audio_chunk) < fs * 2 * 0.5:
            continue

        audio_data = sr.AudioData(audio_chunk, fs, 2)
        print("[システム] 音声を検出しました。文字起こし中...")

        try:
            text = r.recognize_google(audio_data, language="ja-JP")
            touch_activity()
            request_id = begin_request()
            print(f"\nあなた: {text}")
            print("Gemini: (考え中...)")
            # 相槌「はい。」+ うなずき/興味津々(ランダム) + 顔の反応
            queue_delayed_thinking_ack(request_id)

            history_keywords = ["履歴", "過去", "前回", "これまで", "今まで", "話した内容"]
            if is_topic_suggestion_request(text):
                reply = generate_history_topic_suggestion(reason=text)
                append_chat_exchange(text, reply)
            elif is_weather_request(text):
                reply = fetch_tobatti_weather_reply()
                append_chat_exchange(text, reply)
            elif is_news_request(text):
                reply = fetch_tobatti_news_reply()
                append_chat_exchange(text, reply)
            elif is_school_question(text):
                # 学校の質問は学校概要docxを持つ通常ルートで答える(Web検索に回さない)
                reply = send_to_gemini(text)
            elif is_fresh_info_request(text) or is_ldp_president_question(text) or is_general_web_search_request(text):
                reply = fetch_web_latest_reply(text)
                append_chat_exchange(text, reply)
            elif any(kw in text for kw in history_keywords):
                history_snapshot = get_history_snapshot()
                history_summary = "\n".join(
                    f"{'あなた' if c.role == 'user' else ROBOT_NAME}: {c.parts[0].text}"
                    for c in history_snapshot
                )
                extra_context = (
                    "【システム情報】以下がこれまでの会話履歴です。"
                    "この内容を元に質問へ答えてください。\n"
                    f"{history_summary}"
                )
                reply = send_to_gemini(text, extra_context=extra_context)
            else:
                reply = send_to_gemini(text)

            finish_request(request_id)
            clear_pending_tts(kind="thinking_ack")
            print(f"Gemini: {reply}\n")
            print("-" * 40)
            enqueue_tts(reply)
            touch_activity()

        except sr.UnknownValueError:
            print("[システム] 音声は検出しましたが、言葉として認識できませんでした。")
        except sr.RequestError as e:
            print(f"[音声認識エラー] {e}")
        except Exception as e:
            if "request_id" in locals():
                finish_request(request_id)
                clear_pending_tts(kind="thinking_ack")
            print(f"[Geminiエラー] {e}")


def audio_stream_worker():
    """マイク入力ストリームをバックグラウンドで回し続ける"""
    device = os.environ.get("MIC_DEVICE", "").strip() or None
    if device is not None and device.isdigit():
        device = int(device)
    try:
        with sd.RawInputStream(
            samplerate=fs,
            blocksize=int(fs * block_duration),
            dtype="int16",
            channels=1,
            device=device,
            callback=audio_callback,
        ):
            while True:
                sd.sleep(500)
    except Exception as exc:
        print(f"[エラー] マイク入力を開始できませんでした: {exc}")
        print("        MIC_DEVICE の設定や、マイクの接続を確認してください。")

# ==========================================
# 15. 起動時の挨拶
# ==========================================
def startup_greeting_worker():
    if is_first_run:
        print("[システム] 初回起動のため、挨拶メッセージを生成します...")
        try:
            greeting = send_to_gemini(
                f"こんにちは！初めて起動しました。{ROBOT_NAME}として、"
                "東京高専の案内ロボットらしい自己紹介を短くしてください。"
            )
            print(f"Gemini: {greeting}\n")
            print("-" * 40)
            enqueue_tts(greeting, kind="greeting")
        except Exception as e:
            print(f"[Geminiエラー] 挨拶の生成に失敗しました: {e}")
    else:
        print("[システム] 過去の会話履歴から話題候補を生成します...")
        try:
            topic = generate_history_topic_suggestion(reason="起動時の話しかけ")
            append_chat_exchange("起動時の履歴ベース話題提案", topic)
            print(f"Gemini: {topic}\n")
            print("-" * 40)
            enqueue_tts(topic, kind="topic")
        except Exception as e:
            print(f"[Geminiエラー] 話題候補の生成に失敗しました: {e}")

# ==========================================
# 16. メイン処理
# ==========================================
def main():
    print("========================================")
    print(f" {ROBOT_NAME} 統合版を起動しました！")
    print(" 顔表示・会話・動作・天気・ニュースが1つに統合されています。")
    print(" マイクに向かって話しかけてください。")
    print("（終了するには顔ウィンドウで Esc → 閉じる、またはこの画面で Ctrl + C）")
    print("========================================\n")

    threading.Thread(target=tts_worker, daemon=True).start()
    threading.Thread(target=recognize_worker, daemon=True).start()
    threading.Thread(target=audio_stream_worker, daemon=True).start()
    threading.Thread(target=idle_worker, daemon=True).start()
    threading.Thread(target=startup_greeting_worker, daemon=True).start()

    root = tk.Tk()
    FaceWindow(root, face_controller, fullscreen=not FACE_WINDOWED)

    def on_close():
        print("\n終了処理をしています...")
        q.put(None)
        tts_queue.put(None)
        motion_client.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_close()

    print("終了しました。")


if __name__ == "__main__":
    main()
