import argparse
import io
import os
import random
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR / "clock_report"))
sys.path.append(str(BASE_DIR / "news_report"))
sys.path.append(str(BASE_DIR / "weather_report"))

from current_time_speech import save_current_time_text
from fetch_japan_news import fetch_japan_news
from weather_report import save_current_weather_speech


DEFAULT_MOTIONS = ["nod", "wave", "happy", "think", "idle"]
CONFIG_FILE = BASE_DIR / "config.txt"


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


class MotionClient:
    def __init__(self, port, baudrate, motions):
        self.motions = motions
        self.serial = None
        self.lock = threading.Lock()

        if not port:
            print("ESP32 serial port is not set. Motions will be printed only.")
            return

        try:
            import serial

            self.serial = serial.Serial(port, baudrate=baudrate, timeout=1)
            time.sleep(2)
            print(f"Connected to ESP32: {port} ({baudrate}bps)")
        except Exception as exc:
            print(f"Could not open ESP32 serial port. Motions will be printed only: {exc}")

    def play_random(self):
        motion = random.choice(self.motions)
        self.play(motion)
        return motion

    def play(self, motion):
        command = f"{motion}\n"
        with self.lock:
            if self.serial:
                self.serial.write(command.encode("utf-8"))
            print(f"[motion] {motion}")


class Speaker:
    def __init__(self, motion_client, motion_interval=1.8, tts_engine="auto"):
        self.motion_client = motion_client
        self.motion_interval = motion_interval
        self.tts_engine = tts_engine
        self.engine = None
        self.use_powershell_tts = os.name == "nt" and tts_engine in {"auto", "powershell", "sapi"}

        if not self.use_powershell_tts and tts_engine != "none":
            try:
                import pyttsx3

                self.engine = pyttsx3.init()
                self.engine.setProperty("rate", 170)
            except Exception as exc:
                print(f"pyttsx3 is not available. Speech will be printed only: {exc}")

        if self.use_powershell_tts:
            print("TTS engine: Windows PowerShell SAPI")
        elif self.engine:
            print("TTS engine: pyttsx3")
        else:
            print("TTS engine: print only")

    def _motion_loop(self, stop_event):
        while not stop_event.is_set():
            self.motion_client.play_random()
            stop_event.wait(self.motion_interval)

    def say(self, text):
        text = text.strip()
        if not text:
            return

        print(f"[speech] {text}")
        stop_event = threading.Event()
        motion_thread = threading.Thread(target=self._motion_loop, args=(stop_event,), daemon=True)
        motion_thread.start()

        try:
            if self.use_powershell_tts:
                self._say_with_powershell(text)
            elif self.engine:
                self.engine.say(text)
                self.engine.runAndWait()
            else:
                time.sleep(max(1.0, len(text) / 12))
        finally:
            stop_event.set()
            motion_thread.join(timeout=1)

    def _say_with_powershell(self, text):
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


class GeminiChat:
    def __init__(self, api_key, model_name):
        self.chat = None
        self.model = None
        if not api_key:
            print("GEMINI_API_KEY is not set. Gemini replies will use a local fallback.")
            return

        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(model_name)
            self.chat = self.model.start_chat(
                history=[
                    {
                        "role": "user",
                        "parts": [
                            "あなたはコミュニケーションロボットです。短く、自然な日本語で返答してください。"
                        ],
                    },
                    {"role": "model", "parts": ["わかったよ。短く自然に話すね。"]},
                ]
            )
            print(f"Gemini chat is ready: {model_name}")
        except Exception as exc:
            print(f"Gemini initialization failed. Local fallback will be used: {exc}")

    def reply(self, user_text):
        if not self.chat:
            return f"聞いてくれてありがとう。{user_text}について、もう少し教えて。"

        try:
            response = self.chat.send_message(user_text)
            return response.text.strip()
        except Exception as exc:
            return f"ごめんね、今うまく考えられなかった。エラーは {exc} だよ。"

    def short_person_talk(self):
        prompts = [
            "目の前に人がいます。ロボットとして短い一言で自然に話しかけてください。",
            "相手が返事をしなくても自然に聞ける、短い雑談を一文でしてください。",
            "学校や今日の気分について、やさしく短く話しかけてください。",
        ]
        return self.reply(random.choice(prompts))

    def transcribe_audio(self, wav_bytes):
        if not self.model:
            return ""

        try:
            response = self.model.generate_content(
                [
                    "この音声を日本語で文字起こししてください。声が聞き取れない場合は空文字だけ返してください。",
                    {"mime_type": "audio/wav", "data": wav_bytes},
                ]
            )
            return response.text.strip()
        except Exception as exc:
            print(f"[listen] transcription failed: {exc}")
            return ""


class MicrophoneListener:
    def __init__(self, enabled=True, seconds=4.0, samplerate=16000, device=None):
        self.enabled = enabled
        self.seconds = seconds
        self.samplerate = samplerate
        self.device = device

        if not enabled:
            print("Microphone listening is disabled.")
            return

        try:
            import sounddevice  # noqa: F401
            import numpy  # noqa: F401

            print(f"Microphone listening is ready. record_seconds={seconds}")
        except Exception as exc:
            self.enabled = False
            print(f"Microphone listening is not available: {exc}")

    def listen_text(self, gemini):
        if not self.enabled:
            return ""

        try:
            wav_bytes = self._record_wav()
        except Exception as exc:
            print(f"[listen] recording failed: {exc}")
            return ""

        text = gemini.transcribe_audio(wav_bytes)
        text = self._clean_transcript(text)
        if text:
            print(f"[heard] {text}")
        else:
            print("[heard] no speech")
        return text

    def _record_wav(self):
        import numpy as np
        import sounddevice as sd

        frames = int(self.seconds * self.samplerate)
        print("[listen] recording...")
        audio = sd.rec(
            frames,
            samplerate=self.samplerate,
            channels=1,
            dtype="int16",
            device=self.device,
        )
        sd.wait()
        audio = np.asarray(audio, dtype=np.int16)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.samplerate)
            wav.writeframes(audio.tobytes())
        return buffer.getvalue()

    def _clean_transcript(self, text):
        text = text.strip()
        for marker in ["空文字", "聞き取れません", "聞き取れない", "無音"]:
            if marker in text:
                return ""
        return text.strip("「」\"' \n\r\t")


class RealSensePresenceDetector:
    def __init__(self, enabled=True, debug=False, max_distance_m=2.2, min_pixel_ratio=0.04, timeout_ms=100):
        self.debug = debug
        self.max_distance_m = max_distance_m
        self.min_pixel_ratio = min_pixel_ratio
        self.timeout_ms = timeout_ms
        self.pipeline = None
        self.depth_scale = 0.001

        if not enabled:
            print("RealSense detection is disabled.")
            return

        try:
            import pyrealsense2 as rs

            self.pipeline = rs.pipeline()
            config = rs.config()
            config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
            profile = self.pipeline.start(config)
            depth_sensor = profile.get_device().first_depth_sensor()
            self.depth_scale = depth_sensor.get_depth_scale()
            print("RealSense D435 depth stream is ready.")
        except Exception as exc:
            self.pipeline = None
            print(f"RealSense is not available. Presence detection will stay false: {exc}")

    def has_person(self):
        if not self.pipeline:
            return False

        import cv2
        import numpy as np

        frames = self.pipeline.wait_for_frames(timeout_ms=self.timeout_ms)
        depth_frame = frames.get_depth_frame()
        if not depth_frame:
            return False

        depth = np.asanyarray(depth_frame.get_data()) * self.depth_scale
        h, w = depth.shape
        x1, x2 = w // 4, w * 3 // 4
        y1, y2 = h // 5, h * 4 // 5
        roi = depth[y1:y2, x1:x2]
        valid = (roi > 0.25) & (roi < self.max_distance_m)
        ratio = valid.sum() / valid.size
        detected = ratio >= self.min_pixel_ratio

        if self.debug:
            self._show_debug(depth, (x1, y1, x2, y2), ratio, detected, cv2, np)

        return detected

    def _show_debug(self, depth, roi_rect, ratio, detected, cv2, np):
        clipped = np.clip(depth, 0, self.max_distance_m)
        normalized = (255 - (clipped / self.max_distance_m * 255)).astype(np.uint8)
        view = cv2.applyColorMap(normalized, cv2.COLORMAP_JET)

        x1, y1, x2, y2 = roi_rect
        color = (0, 255, 0) if detected else (0, 0, 255)
        cv2.rectangle(view, (x1, y1), (x2, y2), color, 2)
        cv2.putText(view, f"person={detected} ratio={ratio:.3f}", (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        cv2.putText(view, "Press q to close debug view", (18, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.imshow("RealSense Debug", view)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            self.debug = False
            cv2.destroyWindow("RealSense Debug")

    def close(self):
        if self.pipeline:
            self.pipeline.stop()
        if self.debug:
            try:
                import cv2

                cv2.destroyWindow("RealSense Debug")
            except Exception:
                pass


def read_text_file(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return f"読み上げ文の取得に失敗しました。{exc}"


def build_idle_text(kind, args):
    if kind == "time":
        output = BASE_DIR / "clock_report" / "time_speech.txt"
        save_current_time_text(output)
        return read_text_file(output)

    if kind == "weather":
        api_key = os.environ.get("OPENWEATHER_API_KEY")
        if not api_key:
            return "天気APIキーが未設定だから、今は天気を取得できないよ。"
        output = BASE_DIR / "weather_report" / "weather_speech.txt"
        ok = save_current_weather_speech(api_key, args.lat, args.lon, output)
        return read_text_file(output) if ok else "天気を取得できなかったよ。"

    if kind == "news":
        output = BASE_DIR / "news_report" / "news_speech.txt"
        fetch_japan_news(os.environ.get("NEWS_API_KEY", ""), output)
        return read_text_file(output)

    if kind == "trivia":
        return args.gemini.short_person_talk() if hasattr(args, "gemini") else "ちょっとした豆知識だよ。深呼吸をすると、気持ちが少し落ち着きやすくなるよ。"

    return args.gemini.reply("人がいない時に話す、短い自然な雑談を一文で作ってください。") if hasattr(args, "gemini") else "今日はどんなことが起きるかな。少し楽しみだね。"


def build_person_text(gemini, args):
    if random.random() < 0.7:
        return gemini.short_person_talk()
    return build_idle_text(random.choice(["time", "weather", "news", "trivia", "smalltalk"]), args)


def listen_and_reply(listener, gemini, speaker):
    heard = listener.listen_text(gemini)
    if not heard:
        return False
    speaker.say(gemini.reply(heard))
    return True


def parse_args():
    parser = argparse.ArgumentParser(description="Windows side robot controller")
    parser.add_argument("--esp32-port", default=os.environ.get("ESP32_PORT", ""), help="Example: COM3")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--motions", default=",".join(DEFAULT_MOTIONS), help="Motion names sent to ESP32")
    parser.add_argument("--motion-interval", type=float, default=1.8, help="Seconds between motions while speaking")
    parser.add_argument("--tts-engine", default=os.environ.get("TTS_ENGINE", "auto"), choices=["auto", "powershell", "sapi", "pyttsx3", "none"])
    parser.add_argument("--gemini-model", default=os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"))
    parser.add_argument("--lat", type=float, default=35.639249)
    parser.add_argument("--lon", type=float, default=139.29911)
    parser.add_argument("--idle-interval", type=int, default=90, help="Seconds between idle speeches")
    parser.add_argument("--person-talk-interval", type=int, default=int(os.environ.get("PERSON_TALK_INTERVAL", "35")))
    parser.add_argument("--mic-enabled", default=os.environ.get("MIC_ENABLED", "1"), choices=["0", "1"])
    parser.add_argument("--mic-record-seconds", type=float, default=float(os.environ.get("MIC_RECORD_SECONDS", "2.5")))
    parser.add_argument("--mic-device", default=os.environ.get("MIC_DEVICE", "") or None)
    parser.add_argument("--realsense-timeout-ms", type=int, default=int(os.environ.get("REALSENSE_TIMEOUT_MS", "100")))
    parser.add_argument("--no-realsense", action="store_true", help="Run without D435")
    parser.add_argument("--debug-realsense", action="store_true", help="Show RealSense debug window")
    parser.add_argument("--text-chat", action="store_true", help="Use console text input instead of D435")
    return parser.parse_args()


def main():
    load_config_file()
    args = parse_args()
    motions = [item.strip() for item in args.motions.split(",") if item.strip()]
    motion_client = MotionClient(args.esp32_port, args.baudrate, motions or DEFAULT_MOTIONS)
    speaker = Speaker(motion_client, motion_interval=args.motion_interval, tts_engine=args.tts_engine)
    gemini = GeminiChat(os.environ.get("GEMINI_API_KEY"), args.gemini_model)
    args.gemini = gemini
    listener = MicrophoneListener(
        enabled=args.mic_enabled == "1" and not args.text_chat,
        seconds=args.mic_record_seconds,
        device=args.mic_device,
    )
    detector = RealSensePresenceDetector(
        enabled=not args.no_realsense and not args.text_chat,
        debug=args.debug_realsense,
        timeout_ms=args.realsense_timeout_ms,
    )

    speaker.say("起動したよ。近くに人が来たら話しかけるね。")
    last_idle = time.monotonic() - args.idle_interval + 8
    last_person_talk = 0
    person_was_present = False

    try:
        while True:
            if args.text_chat:
                user_text = input("you> ").strip()
                if user_text.lower() in {"exit", "quit"}:
                    break
                speaker.say(gemini.reply(user_text))
                continue

            now = time.monotonic()
            person_present = detector.has_person()

            if person_present:
                if not person_was_present:
                    speaker.say("こんにちは。来てくれてうれしいよ。")
                    listen_and_reply(listener, gemini, speaker)
                    last_person_talk = time.monotonic()
                elif now - last_person_talk >= args.person_talk_interval:
                    if not listen_and_reply(listener, gemini, speaker):
                        speaker.say(build_person_text(gemini, args))
                    last_person_talk = time.monotonic()

                person_was_present = True
                time.sleep(1)
                continue

            person_was_present = False
            if now - last_idle > args.idle_interval:
                idle_kind = random.choice(["time", "weather", "news", "trivia", "smalltalk"])
                speaker.say(build_idle_text(idle_kind, args))
                last_idle = time.monotonic()

            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping robot controller.")
    finally:
        detector.close()


if __name__ == "__main__":
    main()
