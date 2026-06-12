import argparse
import json
import math
import os
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

from animate_face import FaceState, RandomFaceAnimator, make_animation, render_frame


DEFAULT_FACE_COMMAND_FILE = Path(__file__).resolve().parent / "face_state.json"


class FaceAnimationApp:
    def __init__(self, root: tk.Tk, start_fullscreen: bool = True):
        self.root = root
        self.root.title("Robot Face")
        self.root.configure(bg="white")
        self.root.bind("<Escape>", self.exit_fullscreen)
        self.root.bind("<F11>", self.toggle_fullscreen)
        self.root.bind("f", self.toggle_fullscreen)
        self.root.bind("F", self.toggle_fullscreen)
        self.root.bind("a", self.show_angry)
        self.root.bind("A", self.show_angry)
        self.root.bind("b", self.show_sad)
        self.root.bind("B", self.show_sad)

        self.animator = RandomFaceAnimator()
        self.frame_index = 0
        self.running = True
        self.forced_emotion = "neutral"
        self.forced_emotion_until = 0.0
        self.command_file = Path(os.environ.get("FACE_COMMAND_FILE", DEFAULT_FACE_COMMAND_FILE))
        self.command_mtime = 0.0
        self.gaze_active = False
        self.gaze_x = 0.0
        self.gaze_y = 0.0
        self.fps = tk.IntVar(value=10)
        self.size = tk.IntVar(value=512)
        self.seed = tk.StringVar(value="")
        self.gif_seconds = tk.DoubleVar(value=6.0)
        self.current_photo = None

        self._build_ui()
        if start_fullscreen:
            self.enter_fullscreen()
        else:
            self.root.geometry("760x620")
        self._schedule_next_frame()
        self._schedule_command_poll()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        self.preview = tk.Label(main, background="white", anchor="center")
        self.preview.grid(row=0, column=0, sticky="nsew")
        self.preview.bind("<Configure>", self.on_preview_resize)
        self.preview.bind("<ButtonPress-1>", self.start_gaze)
        self.preview.bind("<B1-Motion>", self.update_gaze)
        self.preview.bind("<ButtonRelease-1>", self.stop_gaze)

        controls = ttk.Frame(main)
        controls.grid(row=1, column=0, sticky="ew", pady=(12, 0))

        ttk.Button(controls, text="再生/停止", command=self.toggle_play).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(controls, text="リセット", command=self.reset_animation).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(controls, text="全画面切替", command=self.toggle_fullscreen).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(controls, text="GIF保存", command=self.export_gif).grid(row=0, column=3, padx=(0, 16))

        ttk.Label(controls, text="FPS").grid(row=0, column=4, padx=(0, 4))
        ttk.Spinbox(controls, from_=3, to=30, textvariable=self.fps, width=5).grid(row=0, column=5, padx=(0, 12))

        ttk.Label(controls, text="秒").grid(row=0, column=6, padx=(0, 4))
        ttk.Spinbox(controls, from_=1, to=60, increment=1, textvariable=self.gif_seconds, width=5).grid(
            row=0, column=7, padx=(0, 12)
        )

        ttk.Label(controls, text="サイズ").grid(row=0, column=8, padx=(0, 4))
        ttk.Spinbox(controls, from_=256, to=1024, increment=64, textvariable=self.size, width=6).grid(
            row=0, column=9, padx=(0, 12)
        )

        ttk.Label(controls, text="Seed").grid(row=0, column=10, padx=(0, 4))
        ttk.Entry(controls, textvariable=self.seed, width=8).grid(row=0, column=11)

    def _read_seed(self) -> int | None:
        value = self.seed.get().strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            messagebox.showwarning("Seed", "Seedは整数で入力してください。空欄ならランダムになります。")
            self.seed.set("")
            return None

    def _schedule_next_frame(self) -> None:
        if self.running:
            self.draw_frame()
            self.frame_index += 1

        fps = max(1, self.fps.get())
        self.root.after(int(1000 / fps), self._schedule_next_frame)

    def _schedule_command_poll(self) -> None:
        self._poll_command_file()
        self.root.after(120, self._schedule_command_poll)

    def _poll_command_file(self) -> None:
        try:
            stat = self.command_file.stat()
        except OSError:
            return

        if stat.st_mtime <= self.command_mtime:
            return

        self.command_mtime = stat.st_mtime
        try:
            data = json.loads(self.command_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[face] command read failed: {exc}")
            return

        emotion = str(data.get("face") or data.get("emotion") or "neutral").strip()
        seconds = float(data.get("seconds", 3.0))
        if emotion:
            print(f"[face] emotion={emotion}")
            self._force_emotion(emotion, seconds=seconds)

    def draw_frame(self) -> None:
        state = self.animator.state_for_frame(self.frame_index)
        state = self._apply_forced_emotion(state)
        state = self._apply_gaze(state)
        frame_size = self._current_frame_size()
        frame_bgr = render_frame(state, size=frame_size)
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame_rgb)
        self.current_photo = ImageTk.PhotoImage(image)
        self.preview.configure(image=self.current_photo)

    def _current_frame_size(self) -> int:
        preview_width = max(1, self.preview.winfo_width())
        preview_height = max(1, self.preview.winfo_height())
        requested_size = max(64, self.size.get())
        return min(requested_size, preview_width, preview_height)

    def on_preview_resize(self, event: tk.Event | None = None) -> None:
        if not self.running:
            self.draw_frame()

    def toggle_play(self) -> None:
        self.running = not self.running

    def toggle_fullscreen(self, event: tk.Event | None = None) -> None:
        if bool(self.root.attributes("-fullscreen")):
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def exit_fullscreen(self, event: tk.Event | None = None) -> None:
        self.root.attributes("-fullscreen", False)
        self.root.attributes("-topmost", False)
        self.root.overrideredirect(False)
        self.root.geometry("760x620")

    def enter_fullscreen(self) -> None:
        self.root.overrideredirect(False)
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        self.root.lift()
        self.root.focus_force()
        self.root.after(100, self._enable_borderless_fullscreen)

    def _enable_borderless_fullscreen(self) -> None:
        if not bool(self.root.attributes("-fullscreen")):
            return
        self.root.overrideredirect(True)
        self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        self.root.lift()
        self.root.focus_force()

    def show_angry(self, event: tk.Event | None = None) -> None:
        self._force_emotion("angry")

    def show_sad(self, event: tk.Event | None = None) -> None:
        self._force_emotion("sad")

    def _force_emotion(self, emotion: str, seconds: float = 3.0) -> None:
        self.forced_emotion = emotion
        self.forced_emotion_until = time.monotonic() + max(0.1, seconds)

    def _apply_forced_emotion(self, state: FaceState) -> FaceState:
        if time.monotonic() >= self.forced_emotion_until:
            self.forced_emotion = "neutral"
            return state

        return FaceState(
            left_eye=state.left_eye,
            right_eye=state.right_eye,
            mouth=state.mouth,
            emotion=self.forced_emotion,
            gaze_x=state.gaze_x,
            gaze_y=state.gaze_y,
        )

    def start_gaze(self, event: tk.Event) -> None:
        self.gaze_active = True
        self.update_gaze(event)

    def update_gaze(self, event: tk.Event) -> None:
        if not self.gaze_active:
            return

        center_x = max(1, self.preview.winfo_width() / 2)
        center_y = max(1, self.preview.winfo_height() / 2)
        dx = event.x - center_x
        dy = event.y - center_y
        distance = math.hypot(dx, dy)

        if distance < 1:
            self.gaze_x = 0.0
            self.gaze_y = 0.0
            return

        self.gaze_x = dx / distance
        self.gaze_y = dy / distance

    def stop_gaze(self, event: tk.Event | None = None) -> None:
        self.gaze_active = False
        self.gaze_x = 0.0
        self.gaze_y = 0.0

    def _apply_gaze(self, state: FaceState) -> FaceState:
        if not self.gaze_active:
            return state

        return FaceState(
            left_eye=state.left_eye,
            right_eye=state.right_eye,
            mouth=state.mouth,
            emotion=state.emotion,
            gaze_x=self.gaze_x,
            gaze_y=self.gaze_y,
        )

    def reset_animation(self) -> None:
        self.animator = RandomFaceAnimator(self._read_seed())
        self.frame_index = 0
        self.forced_emotion = "neutral"
        self.forced_emotion_until = 0.0
        self.stop_gaze()
        self.draw_frame()

    def export_gif(self) -> None:
        output_path = filedialog.asksaveasfilename(
            title="GIFを保存",
            defaultextension=".gif",
            filetypes=[("GIF animation", "*.gif")],
            initialfile="face_animation.gif",
        )
        if not output_path:
            return

        try:
            make_animation(
                output_path=Path(output_path),
                seconds=self.gif_seconds.get(),
                fps=max(1, self.fps.get()),
                size=self.size.get(),
                seed=self._read_seed(),
                reference_path=None,
                show_reference=False,
            )
        except Exception as exc:
            messagebox.showerror("GIF保存", f"GIF保存に失敗しました。\n{exc}")
            return

        messagebox.showinfo("GIF保存", f"保存しました:\n{output_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="Robot face UI")
    parser.add_argument("--windowed", action="store_true", help="通常ウィンドウで起動する")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = tk.Tk()
    FaceAnimationApp(root, start_fullscreen=not args.windowed)
    root.mainloop()


if __name__ == "__main__":
    main()
