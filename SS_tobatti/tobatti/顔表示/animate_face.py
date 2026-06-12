import argparse
import math
import random
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


BG_COLOR = (255, 255, 255)
INK_COLOR = (34, 25, 22)


@dataclass
class FaceState:
    left_eye: str = "open"
    right_eye: str = "open"
    mouth: str = "smile"
    emotion: str = "neutral"
    gaze_x: float = 0.0
    gaze_y: float = 0.0


class RandomFaceAnimator:
    def __init__(self, seed: int | None = None):
        self.random = random.Random(seed)
        self.left_blink_until = 0
        self.right_blink_until = 0
        self.next_left_blink = self._next_blink_frame(0)
        self.next_right_blink = self._next_blink_frame(8)
        self.next_mouth = 0
        self.mouth_state = "smile"

    def _next_blink_frame(self, current_frame: int) -> int:
        return current_frame + self.random.randint(25, 80)

    def _choose_mouth(self) -> str:
        return self.random.choices(
            ["closed", "small_open", "wide_open", "smile"],
            weights=[0.32, 0.28, 0.18, 0.22],
            k=1,
        )[0]

    def state_for_frame(self, frame_index: int) -> FaceState:
        if frame_index >= self.next_left_blink:
            duration = self.random.randint(2, 4)
            self.left_blink_until = frame_index + duration
            if self.random.random() < 0.72:
                self.right_blink_until = max(self.right_blink_until, frame_index + duration)
                self.next_right_blink = self._next_blink_frame(self.right_blink_until)
            self.next_left_blink = self._next_blink_frame(self.left_blink_until)

        if frame_index >= self.next_right_blink:
            duration = self.random.randint(2, 4)
            self.right_blink_until = frame_index + duration
            if self.random.random() < 0.72:
                self.left_blink_until = max(self.left_blink_until, frame_index + duration)
                self.next_left_blink = self._next_blink_frame(self.left_blink_until)
            self.next_right_blink = self._next_blink_frame(self.right_blink_until)

        left_eye = "closed" if frame_index < self.left_blink_until else "open"
        right_eye = "closed" if frame_index < self.right_blink_until else "open"

        if frame_index >= self.next_mouth:
            self.mouth_state = self._choose_mouth()
            self.next_mouth = frame_index + self.random.randint(8, 22)

        return FaceState(left_eye=left_eye, right_eye=right_eye, mouth=self.mouth_state)


def draw_eye(
    image: np.ndarray,
    center: tuple[int, int],
    state: str,
    scale: float,
    emotion: str = "neutral",
    gaze: tuple[float, float] = (0.0, 0.0),
) -> None:
    cx, cy = center
    outer = int(42 * scale)
    thickness = max(4, int(7 * scale))

    if state == "closed":
        cv2.ellipse(
            image,
            (cx, cy + int(4 * scale)),
            (outer, int(outer * 0.33)),
            0,
            0,
            180,
            INK_COLOR,
            thickness,
            cv2.LINE_AA,
        )
        draw_eyebrow(image, center, emotion, scale)
        return

    cv2.circle(image, (cx, cy), outer, INK_COLOR, thickness, cv2.LINE_AA)
    gaze_x = max(-1.0, min(1.0, gaze[0]))
    gaze_y = max(-1.0, min(1.0, gaze[1]))
    pupil_x = cx + int(gaze_x * 16 * scale)
    pupil_y = cy + int((5 + gaze_y * 12) * scale)
    cv2.circle(image, (pupil_x, pupil_y), int(14 * scale), INK_COLOR, -1, cv2.LINE_AA)
    cv2.circle(
        image,
        (pupil_x - int(5 * scale), pupil_y - int(5 * scale)),
        int(4 * scale),
        BG_COLOR,
        -1,
        cv2.LINE_AA,
    )
    draw_eyebrow(image, center, emotion, scale)


def draw_eyebrow(image: np.ndarray, center: tuple[int, int], emotion: str, scale: float) -> None:
    if emotion not in {"angry", "sad", "thinking"}:
        return

    cx, cy = center
    thickness = max(4, int(7 * scale))
    y = cy - int(58 * scale)
    x1 = cx - int(36 * scale)
    x2 = cx + int(36 * scale)

    if emotion == "thinking":
        if cx < image.shape[1] // 2:
            p1, p2 = (x1, y - int(4 * scale)), (x2, y + int(2 * scale))
        else:
            p1, p2 = (x1, y + int(2 * scale)), (x2, y - int(4 * scale))
    elif emotion == "angry":
        if cx < image.shape[1] // 2:
            p1, p2 = (x1, y - int(10 * scale)), (x2, y + int(12 * scale))
        else:
            p1, p2 = (x1, y + int(12 * scale)), (x2, y - int(10 * scale))
    else:
        if cx < image.shape[1] // 2:
            p1, p2 = (x1, y + int(12 * scale)), (x2, y - int(10 * scale))
        else:
            p1, p2 = (x1, y - int(10 * scale)), (x2, y + int(12 * scale))

    cv2.line(image, p1, p2, INK_COLOR, thickness, cv2.LINE_AA)


def draw_mouth(image: np.ndarray, state: str, scale: float, emotion: str = "neutral") -> None:
    thickness = max(4, int(8 * scale))
    center = (image.shape[1] // 2, int(260 * scale))

    if emotion == "angry":
        cv2.line(
            image,
            (center[0] - int(48 * scale), center[1] + int(12 * scale)),
            (center[0] + int(48 * scale), center[1] - int(12 * scale)),
            INK_COLOR,
            thickness,
            cv2.LINE_AA,
        )
        return

    if emotion == "sad":
        cv2.ellipse(
            image,
            (center[0], center[1] + int(42 * scale)),
            (int(70 * scale), int(46 * scale)),
            0,
            200,
            340,
            INK_COLOR,
            thickness,
            cv2.LINE_AA,
        )
        return

    if emotion == "happy":
        cv2.ellipse(
            image,
            center,
            (int(86 * scale), int(56 * scale)),
            0,
            18,
            162,
            INK_COLOR,
            thickness,
            cv2.LINE_AA,
        )
        return

    if emotion == "thinking":
        cv2.ellipse(
            image,
            (center[0], center[1] + int(8 * scale)),
            (int(28 * scale), int(22 * scale)),
            0,
            0,
            360,
            INK_COLOR,
            thickness,
            cv2.LINE_AA,
        )
        return

    if emotion == "explain":
        cv2.ellipse(
            image,
            center,
            (int(46 * scale), int(36 * scale)),
            -8,
            0,
            360,
            INK_COLOR,
            thickness,
            cv2.LINE_AA,
        )
        return

    if state == "closed":
        cv2.line(
            image,
            (center[0] - int(42 * scale), center[1]),
            (center[0] + int(42 * scale), center[1]),
            INK_COLOR,
            thickness,
            cv2.LINE_AA,
        )
        return

    if state == "small_open":
        cv2.ellipse(
            image,
            center,
            (int(25 * scale), int(34 * scale)),
            -8,
            0,
            360,
            INK_COLOR,
            thickness,
            cv2.LINE_AA,
        )
        return

    if state == "wide_open":
        points = np.array(
            [
                (center[0] - int(68 * scale), center[1] - int(26 * scale)),
                (center[0] + int(72 * scale), center[1] - int(28 * scale)),
                (center[0] + int(36 * scale), center[1] + int(52 * scale)),
                (center[0] - int(30 * scale), center[1] + int(50 * scale)),
            ],
            dtype=np.int32,
        )
        cv2.polylines(image, [points], True, INK_COLOR, thickness, cv2.LINE_AA)
        return

    cv2.ellipse(
        image,
        center,
        (int(72 * scale), int(46 * scale)),
        0,
        20,
        160,
        INK_COLOR,
        thickness,
        cv2.LINE_AA,
    )


def render_frame(state: FaceState, size: int = 512) -> np.ndarray:
    scale = size / 360
    image = np.full((size, size, 3), BG_COLOR, dtype=np.uint8)

    left_eye = (int(132 * scale), int(140 * scale))
    right_eye = (int(228 * scale), int(140 * scale))

    gaze = (state.gaze_x, state.gaze_y)
    draw_eye(image, left_eye, state.left_eye, scale, state.emotion, gaze)
    draw_eye(image, right_eye, state.right_eye, scale, state.emotion, gaze)
    draw_mouth(image, state.mouth, scale, state.emotion)

    return image


def add_reference_preview(frame: np.ndarray, reference_path: Path | None) -> np.ndarray:
    if reference_path is None or not reference_path.exists():
        return frame

    reference = cv2.imdecode(np.fromfile(str(reference_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if reference is None:
        return frame

    h, w = frame.shape[:2]
    preview_w = int(w * 0.3)
    preview_h = max(1, int(reference.shape[0] * preview_w / reference.shape[1]))
    preview = cv2.resize(reference, (preview_w, preview_h), interpolation=cv2.INTER_AREA)

    x0 = w - preview_w - 12
    y0 = h - preview_h - 12
    frame[y0 : y0 + preview_h, x0 : x0 + preview_w] = preview
    cv2.rectangle(frame, (x0, y0), (x0 + preview_w, y0 + preview_h), (220, 220, 220), 1)
    return frame


def save_gif(frames_bgr: list[np.ndarray], output_path: Path, fps: int) -> None:
    duration_ms = int(1000 / fps)
    frames_rgb = [cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) for frame in frames_bgr]
    pil_frames = [Image.fromarray(frame) for frame in frames_rgb]
    pil_frames[0].save(
        output_path,
        save_all=True,
        append_images=pil_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )


def make_animation(
    output_path: Path,
    seconds: float,
    fps: int,
    size: int,
    seed: int | None,
    reference_path: Path | None,
    show_reference: bool,
) -> None:
    animator = RandomFaceAnimator(seed)
    total_frames = max(1, math.ceil(seconds * fps))
    frames = []

    for frame_index in range(total_frames):
        state = animator.state_for_frame(frame_index)
        frame = render_frame(state, size=size)
        if show_reference:
            frame = add_reference_preview(frame, reference_path)
        frames.append(frame)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_gif(frames, output_path, fps)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenCVでランダムな瞬きと口パクを描画し、GIFアニメーションを作成します。"
    )
    parser.add_argument("--output", default="output/face_animation.gif", help="出力GIFのパス")
    parser.add_argument("--seconds", type=float, default=5.0, help="GIFの長さ")
    parser.add_argument("--fps", type=int, default=12, help="1秒あたりのフレーム数")
    parser.add_argument("--size", type=int, default=512, help="画像サイズ(px)。正方形で出力します")
    parser.add_argument("--seed", type=int, default=None, help="乱数シード。固定すると同じ動きになります")
    parser.add_argument(
        "--reference",
        default="顔の画像の種類.jpg",
        help="参考画像のパス。--show-reference指定時だけ右下に表示します",
    )
    parser.add_argument(
        "--show-reference",
        action="store_true",
        help="参考画像を右下に小さく重ねます。通常の提出用GIFでは指定しないでください",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    make_animation(
        output_path=Path(args.output),
        seconds=args.seconds,
        fps=args.fps,
        size=args.size,
        seed=args.seed,
        reference_path=Path(args.reference) if args.reference else None,
        show_reference=args.show_reference,
    )
    print(f"GIFを作成しました: {args.output}")


if __name__ == "__main__":
    main()
