import argparse
import io
import json
import math
import os
import random
import subprocess
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.txt"
DEFAULT_HISTORY_FILE = BASE_DIR / "conversation_history.jsonl"

SYSTEM_PROMPT = """
あなたは学校や展示で動くコミュニケーションロボット「トバッティ」です。
日本語で、短く、自然に、やさしく返答してください。
返答は原則1文、長くても2文です。
音声読み上げに向かない記号、箇条書き、長い説明は避けてください。
過去の会話履歴があれば自然に参照してください。ただし毎回むりに触れなくてよいです。
"""

AIZUCHI = [
    "うん。",
    "なるほど。",
    "聞いてるよ。",
    "そっか。",
    "いいね。",
]


def load_config_file(path=CONFIG_FILE):
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if key and value and key not in os.environ:
            os.environ[key] = value


class ConversationStore:
    def __init__(self, path=DEFAULT_HISTORY_FILE, max_turns=12):
        self.path = Path(path)
        self.max_turns = max_turns

    def append(self, user_text, robot_text, source="voice"):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "user": user_text,
            "robot": robot_text,
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_recent(self):
        if not self.path.exists():
            return []

        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("user") or record.get("robot"):
                records.append(record)
        return records[-self.max_turns :]

    def print_recent(self):
        records = self.load_recent()
        if not records:
            print("会話履歴はまだありません。")
            return

        print(f"会話履歴: {self.path}")
        for record in records:
            timestamp = record.get("timestamp", "")
            user_text = record.get("user", "")
            robot_text = record.get("robot", "")
            print(f"[{timestamp}] you> {user_text}")
            print(f"[{timestamp}] robot> {robot_text}")


class Speaker:
    def __init__(self, rate=175, volume=1.0, enabled=True, engine_name="powershell"):
        self.enabled = enabled
        self.engine = None
        self.engine_name = engine_name
        if not enabled:
            print("[tts] 読み上げなしで実行します。")
            return

        if engine_name in {"powershell", "sapi"}:
            print("[tts] Windows SAPI を使います。")
            return

        if engine_name in {"auto", "pyttsx3"}:
            try:
                import pyttsx3

                self.engine = pyttsx3.init()
                self.engine.setProperty("rate", rate)
                self.engine.setProperty("volume", volume)
                print("[tts] pyttsx3 を使います。")
            except Exception as exc:
                print(f"[tts] pyttsx3 が使えないため Windows SAPI に切り替えます: {exc}")

    def say(self, text, label="robot"):
        text = clean_text(text)
        if not text:
            return

        print(f"{label}> {text}")
        if not self.enabled:
            return

        if self.engine:
            self.engine.say(text)
            self.engine.runAndWait()
            return

        if os.name != "nt":
            return

        escaped = text.replace("'", "''")
        command = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Rate = 0; "
            "$s.Volume = 100; "
            f"$s.Speak('{escaped}')"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            check=False,
        )


class VoiceActivityMicrophone:
    def __init__(
        self,
        samplerate=16000,
        device=None,
        chunk_ms=80,
        silence_ms=500,
        max_seconds=6.0,
        min_seconds=0.35,
        threshold=None,
        debug_level=False,
    ):
        self.samplerate = samplerate
        self.device = self._normalize_device(device)
        self.chunk_ms = chunk_ms
        self.chunk_frames = max(1, int(samplerate * chunk_ms / 1000))
        self.silence_chunks = max(1, int(silence_ms / chunk_ms))
        self.max_chunks = max(1, int(max_seconds * 1000 / chunk_ms))
        self.min_chunks = max(1, int(min_seconds * 1000 / chunk_ms))
        self.threshold = threshold
        self.debug_level = debug_level

    def _normalize_device(self, device):
        if device in {None, ""}:
            return None

        try:
            device = int(device)
        except (TypeError, ValueError):
            pass

        try:
            import sounddevice as sd

            info = sd.query_devices(device, "input")
            if info.get("max_input_channels", 0) <= 0:
                raise ValueError("input channels are 0")
            return device
        except Exception as exc:
            print(f"[mic] MIC_DEVICE={device} は使えません。既定マイクに戻します: {exc}")
            return None

    def calibrate(self):
        if self.threshold is not None:
            return

        import numpy as np
        import sounddevice as sd

        print("[mic] 周囲音を確認中です。1秒だけ静かにしてください...")
        audio = sd.rec(
            int(self.samplerate * 1.0),
            samplerate=self.samplerate,
            channels=1,
            dtype="int16",
            device=self.device,
        )
        sd.wait()
        rms = self._rms(np.asarray(audio, dtype=np.int16))
        self.threshold = min(180.0, max(50.0, rms * 1.5))
        print(f"[mic] 周囲音レベル: {rms:.0f} / 音声検知しきい値: {self.threshold:.0f}")

    def listen_utterance(self):
        import numpy as np
        import sounddevice as sd

        self.calibrate()
        print("[mic] 待ち受け中です。話し始めてください... (Ctrl+Cで終了)")

        frames = []
        speech_started = False
        silent_chunks = 0
        speech_chunks = 0
        wait_chunks = 0

        with sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="int16",
            blocksize=self.chunk_frames,
            device=self.device,
        ) as stream:
            while True:
                chunk, _ = stream.read(self.chunk_frames)
                chunk = np.asarray(chunk, dtype=np.int16)
                level = self._rms(chunk)
                loud = level >= self.threshold

                if not speech_started:
                    wait_chunks += 1
                    if self.debug_level and wait_chunks % 25 == 0:
                        print(f"[mic] input level={level:.0f} threshold={self.threshold:.0f}")
                    if loud:
                        speech_started = True
                        frames.append(chunk.copy())
                        speech_chunks = 1
                        silent_chunks = 0
                        print("[mic] 録音中...")
                    continue

                frames.append(chunk.copy())
                speech_chunks += 1

                if loud:
                    silent_chunks = 0
                else:
                    silent_chunks += 1

                enough_audio = speech_chunks >= self.min_chunks
                end_by_silence = enough_audio and silent_chunks >= self.silence_chunks
                end_by_length = speech_chunks >= self.max_chunks
                if end_by_silence or end_by_length:
                    break

        audio = np.concatenate(frames, axis=0)
        return self._to_wav(audio)

    def _to_wav(self, audio):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.samplerate)
            wav.writeframes(audio.tobytes())
        return buffer.getvalue()

    def _rms(self, audio):
        if audio.size == 0:
            return 0.0
        values = audio.astype("float32")
        return math.sqrt(float((values * values).mean()))


class GeminiVoiceChat:
    def __init__(self, api_key, model_name, store):
        if not api_key or api_key == "your_gemini_api_key_here":
            raise RuntimeError("GEMINI_API_KEY が設定されていません。config.txt に Gemini API キーを入れてください。")

        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self.genai = genai
        self.model_name = model_name
        self.fallback_model_names = [
            model_name,
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
        ]
        self.fallback_model_names = list(dict.fromkeys(self.fallback_model_names))
        self.model = genai.GenerativeModel(model_name)
        self.store = store
        self.records = store.load_recent()
        self.generation_config = {
            "temperature": 0.6,
            "max_output_tokens": 120,
        }
        self.text_chat = self.model.start_chat(
            history=[
                {"role": "user", "parts": [SYSTEM_PROMPT]},
                {"role": "model", "parts": ["わかりました。短く自然な日本語で会話します。"]},
            ]
        )
        print(f"[history] {len(self.records)}件の過去会話を読み込みました: {store.path}")
        print(f"[model] {self.model_name}")

    def reply_text(self, user_text):
        response = self._send_text(user_text)
        reply = clean_text(response.text)
        self._remember(user_text, reply, source="text")
        return reply

    def reply_audio(self, wav_bytes):
        history_text = format_history(self.records[-8:])
        prompt = f"""
{SYSTEM_PROMPT}

過去の会話履歴:
{history_text or "まだありません。"}

添付された音声を聞き取り、その発話に会話として返答してください。
必ず次の2行だけで返してください。Markdownや説明は不要です。

聞き取り: 聞き取った日本語
返答: トバッティとしての短い返答

聞き取れない場合は次のように返してください。
聞き取り:
返答: ごめんね、今の声が聞き取れませんでした。もう一度話してくれる？
"""
        response = self._generate_audio_reply(prompt, wav_bytes)
        transcript, reply = parse_audio_response(response.text)
        self._remember(transcript or "音声入力", reply, source="voice")
        return transcript, reply

    def _send_text(self, user_text):
        last_error = None
        for model_name in self.fallback_model_names:
            self._select_model(model_name)
            try:
                return self.text_chat.send_message(user_text, generation_config=self.generation_config)
            except Exception as exc:
                last_error = exc
                if not is_model_not_found_error(exc):
                    raise
        raise last_error

    def _generate_audio_reply(self, prompt, wav_bytes):
        last_error = None
        for model_name in self.fallback_model_names:
            self._select_model(model_name)
            try:
                return self.model.generate_content(
                    [
                        prompt,
                        {"mime_type": "audio/wav", "data": wav_bytes},
                    ],
                    generation_config=self.generation_config,
                )
            except Exception as exc:
                last_error = exc
                if not is_model_not_found_error(exc):
                    raise
                print(f"[model] {model_name} が使えないため別モデルを試します。")
        raise last_error

    def _select_model(self, model_name):
        if model_name == self.model_name:
            return
        self.model_name = model_name
        self.model = self.genai.GenerativeModel(model_name)
        self.text_chat = self.model.start_chat(
            history=[
                {"role": "user", "parts": [SYSTEM_PROMPT]},
                {"role": "model", "parts": ["わかりました。短く自然な日本語で会話します。"]},
            ]
        )
        print(f"[model] switched to {model_name}")

    def _remember(self, user_text, reply, source):
        if not reply:
            return
        self.store.append(user_text, reply, source=source)
        self.records.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "source": source,
                "user": user_text,
                "robot": reply,
            }
        )
        self.records = self.records[-self.store.max_turns :]


def format_history(records):
    lines = []
    for record in records:
        user_text = record.get("user", "")
        robot_text = record.get("robot", "")
        if user_text:
            lines.append(f"相手: {user_text}")
        if robot_text:
            lines.append(f"トバッティ: {robot_text}")
    return "\n".join(lines)


def clean_text(text):
    text = (text or "").strip()
    if text in {"", "空文字", "聞き取れません", "聞き取れませんでした"}:
        return ""
    return text.strip("「」\"' \n\r\t")


def parse_audio_response(text):
    transcript = ""
    reply = ""

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if line.startswith("聞き取り:"):
            transcript = clean_text(line.split(":", 1)[1])
        elif line.startswith("聞き取り："):
            transcript = clean_text(line.split("：", 1)[1])
        elif line.startswith("返答:"):
            reply = clean_text(line.split(":", 1)[1])
        elif line.startswith("返答："):
            reply = clean_text(line.split("：", 1)[1])

    if not reply:
        reply = clean_text(text)
    return transcript, reply


def is_model_not_found_error(exc):
    message = str(exc).lower()
    return "404" in message and ("not found" in message or "not supported" in message)


def list_devices():
    import sounddevice as sd

    print(sd.query_devices())
    print()
    print("Default device:")
    print(sd.default.device)


def parse_args():
    parser = argparse.ArgumentParser(description="Voice-only conversation for the communication robot")
    parser.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    parser.add_argument("--samplerate", type=int, default=int(os.environ.get("MIC_SAMPLE_RATE", "16000")))
    parser.add_argument("--mic-device", default=os.environ.get("MIC_DEVICE", "") or None)
    parser.add_argument("--silence-ms", type=int, default=int(os.environ.get("MIC_SILENCE_MS", "500")))
    parser.add_argument("--max-seconds", type=float, default=float(os.environ.get("MIC_MAX_SECONDS", "6.0")))
    parser.add_argument("--threshold", type=float, default=float(os.environ["MIC_THRESHOLD"]) if os.environ.get("MIC_THRESHOLD") else None)
    parser.add_argument("--debug-level", action="store_true", default=os.environ.get("MIC_DEBUG", "0") == "1")
    parser.add_argument("--tts-engine", default=os.environ.get("TTS_ENGINE", "powershell"), choices=["powershell", "sapi", "pyttsx3", "auto"])
    parser.add_argument("--history-file", default=os.environ.get("CONVERSATION_HISTORY_FILE", str(DEFAULT_HISTORY_FILE)))
    parser.add_argument("--history-turns", type=int, default=int(os.environ.get("CONVERSATION_HISTORY_TURNS", "12")))
    parser.add_argument("--text", action="store_true", help="Use keyboard input instead of microphone")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    parser.add_argument("--show-history", action="store_true", help="Show recent saved conversation history and exit")
    parser.add_argument("--no-tts", action="store_true", help="Print replies without reading them aloud")
    return parser.parse_args()


def run_text_loop(chat, speaker):
    print("テキスト会話モードです。終了するには exit と入力してください。")
    while True:
        user_text = input("you> ").strip()
        if user_text.lower() in {"exit", "quit", "q"}:
            break
        if user_text:
            speaker.say(chat.reply_text(user_text))


def run_voice_loop(chat, speaker, microphone):
    print("リアルタイム音声会話モードです。Enterは不要です。Ctrl+Cで終了します。")
    speaker.say("こんにちは。話しかけてください。")

    with ThreadPoolExecutor(max_workers=1) as executor:
        while True:
            started = time.monotonic()
            wav_bytes = microphone.listen_utterance()
            print("[ai] 返答を考えています...")
            future = executor.submit(chat.reply_audio, wav_bytes)
            speaker.say(random.choice(AIZUCHI), label="aizuchi")
            try:
                transcript, reply = future.result()
            except Exception as exc:
                print(f"[ERROR] Gemini応答に失敗しました: {exc}")
                speaker.say("ごめんね、今うまく考えられませんでした。もう一度話してくれる？")
                continue

            if transcript:
                print(f"you> {transcript}")
            else:
                print("you> [聞き取れませんでした]")

            if not reply:
                reply = "ごめんね、今の声が聞き取れませんでした。もう一度話してくれる？"

            print(f"[latency] AI応答まで {time.monotonic() - started:.1f}秒")
            speaker.say(reply)


def main():
    load_config_file()
    args = parse_args()
    store = ConversationStore(args.history_file, max_turns=args.history_turns)

    if args.list_devices:
        list_devices()
        return 0

    if args.show_history:
        store.print_recent()
        return 0

    try:
        chat = GeminiVoiceChat(os.environ.get("GEMINI_API_KEY", ""), args.model, store)
    except Exception as exc:
        print(f"[ERROR] Gemini を初期化できませんでした: {exc}")
        return 1

    speaker = Speaker(enabled=not args.no_tts, engine_name=args.tts_engine)

    if args.text:
        run_text_loop(chat, speaker)
        return 0

    try:
        microphone = VoiceActivityMicrophone(
            samplerate=args.samplerate,
            device=args.mic_device,
            silence_ms=args.silence_ms,
            max_seconds=args.max_seconds,
            threshold=args.threshold,
            debug_level=args.debug_level,
        )
        run_voice_loop(chat, speaker, microphone)
    except KeyboardInterrupt:
        print("\n終了します。")
    except Exception as exc:
        print(f"[ERROR] マイク録音に失敗しました: {exc}")
        print("マイク一覧は run_voice_conversation.bat の 3 番、または voice_conversation.py --list-devices で確認できます。")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
