"""
RealSense D435 空間マップ生成
==============================
Intel RealSense D435 を使って深度データを取得し、
3D 点群（空間マップ）をリアルタイムで生成・保存するスクリプト。

依存ライブラリのインストール:
    pip install pyrealsense2 numpy opencv-python open3d

使い方:
    python realsense_spatial_map.py [オプション]

    -m, --mode      動作モード: live / record / playback (デフォルト: live)
    -o, --output    保存先ディレクトリ (デフォルト: ./output)
    -b, --bag       .bag ファイルパス (playback モード時に必須)
    --no-viz        Open3D リアルタイム可視化を無効化
    --fps           フレームレート (デフォルト: 30)
    --width         カラー解像度 幅 (デフォルト: 848)
    --height        カラー解像度 高さ (デフォルト: 480)
"""

import argparse
import os
import sys
import time
from pathlib import Path
from datetime import datetime

import numpy as np
import cv2

try:
    import pyrealsense2 as rs
except ImportError:
    sys.exit("[ERROR] pyrealsense2 が見つかりません。\n  pip install pyrealsense2")

try:
    import open3d as o3d
    HAS_OPEN3D = True
except ImportError:
    HAS_OPEN3D = False
    print("[WARN] open3d が見つかりません。3D 可視化は無効です。\n  pip install open3d")


# ─────────────────────────────────────────────
#  カラーマップ ユーティリティ
# ─────────────────────────────────────────────

def depth_to_colormap(depth_frame, min_dist=0.1, max_dist=5.0):
    """深度フレームを BGR カラーマップ画像へ変換"""
    depth_image = np.asanyarray(depth_frame.get_data()).astype(np.float32)
    depth_scale  = depth_frame.get_units()  # メートル/カウント
    depth_m      = depth_image * depth_scale

    # 範囲外をクリップ → 0–255 に正規化
    depth_clipped = np.clip(depth_m, min_dist, max_dist)
    depth_norm    = ((depth_clipped - min_dist) / (max_dist - min_dist) * 255).astype(np.uint8)
    colormap      = cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)

    # 無効ピクセル（距離=0）はグレーで塗る
    invalid_mask        = (depth_image == 0)
    colormap[invalid_mask] = [60, 60, 60]
    return colormap, depth_m


# ─────────────────────────────────────────────
#  点群生成
# ─────────────────────────────────────────────

def frames_to_pointcloud(depth_frame, color_frame, pc: rs.pointcloud):
    """RealSense フレームペア → Open3D PointCloud"""
    pc.map_to(color_frame)
    points = pc.calculate(depth_frame)

    vtx   = np.asanyarray(points.get_vertices()).view(np.float32).reshape(-1, 3)
    uvmap = np.asanyarray(points.get_texture_coordinates()).view(np.float32).reshape(-1, 2)

    # カラー画像からテクスチャを取得
    color_image = np.asanyarray(color_frame.get_data())  # BGR
    h, w        = color_image.shape[:2]

    u = np.clip((uvmap[:, 0] * w).astype(int), 0, w - 1)
    v = np.clip((uvmap[:, 1] * h).astype(int), 0, h - 1)
    colors = color_image[v, u, ::-1] / 255.0  # BGR → RGB, 0–1

    # 無効点（z=0）を除去
    valid   = vtx[:, 2] > 0
    vtx     = vtx[valid]
    colors  = colors[valid]

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(vtx)
    pcd.colors = o3d.utility.Vector3dVector(colors)
    return pcd


# ─────────────────────────────────────────────
#  パイプライン設定
# ─────────────────────────────────────────────

def build_pipeline(mode: str, bag_path: str | None, fps: int, width: int, height: int):
    """RS パイプラインを構築して開始"""
    pipeline = rs.pipeline()
    config   = rs.config()

    if mode == "playback":
        if not bag_path or not Path(bag_path).exists():
            sys.exit(f"[ERROR] .bag ファイルが見つかりません: {bag_path}")
        rs.config.enable_device_from_file(config, bag_path, repeat_playback=False)
        print(f"[INFO] Playback: {bag_path}")
    else:
        config.enable_stream(rs.stream.depth,  width, height, rs.format.z16,  fps)
        config.enable_stream(rs.stream.color,  width, height, rs.format.bgr8, fps)

        if mode == "record":
            ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
            bag_file = f"record_{ts}.bag"
            config.enable_record_to_file(bag_file)
            print(f"[INFO] 録画開始: {bag_file}")

    profile  = pipeline.start(config)
    return pipeline, profile


# ─────────────────────────────────────────────
#  メインループ
# ─────────────────────────────────────────────

def run(args):
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    pipeline, profile = build_pipeline(
        args.mode, args.bag, args.fps, args.width, args.height
    )

    # 深度スケール・アライン
    depth_sensor = profile.get_device().first_depth_sensor()
    align        = rs.align(rs.stream.color)
    pc_calc      = rs.pointcloud()

    # ホールフィリング / 空間フィルター
    spatial_filter   = rs.spatial_filter()
    temporal_filter  = rs.temporal_filter()
    hole_fill_filter = rs.hole_filling_filter()

    spatial_filter.set_option(rs.option.filter_magnitude,   2)
    spatial_filter.set_option(rs.option.filter_smooth_alpha, 0.5)

    # Open3D ビジュアライザ
    viz = None
    pcd_vis = None
    if HAS_OPEN3D and not args.no_viz:
        viz     = o3d.visualization.Visualizer()
        viz.create_window("RealSense D435 — 空間マップ", width=1280, height=720)
        pcd_vis = o3d.geometry.PointCloud()
        viz.add_geometry(pcd_vis)
        opt = viz.get_render_option()
        opt.point_size           = 1.5
        opt.background_color     = np.array([0.05, 0.05, 0.05])
        opt.show_coordinate_frame = True

    print("\n[INFO] ストリーミング開始")
    print("  [S]  点群を .ply として保存")
    print("  [D]  深度画像を PNG として保存")
    print("  [Q / ESC]  終了\n")

    frame_count   = 0
    save_count    = 0
    fps_timer     = time.time()
    displayed_fps = 0.0

    try:
        while True:
            frames = pipeline.wait_for_frames(timeout_ms=5000)
            frames = align.process(frames)

            depth_frame = frames.get_depth_frame()
            color_frame = frames.get_color_frame()
            if not depth_frame or not color_frame:
                continue

            # フィルター適用
            depth_frame = spatial_filter.process(depth_frame)
            depth_frame = temporal_filter.process(depth_frame)
            depth_frame = hole_fill_filter.process(depth_frame)
            depth_frame = depth_frame.as_depth_frame()

            frame_count += 1

            # FPS 計算
            elapsed = time.time() - fps_timer
            if elapsed >= 1.0:
                displayed_fps = frame_count / elapsed
                frame_count   = 0
                fps_timer     = time.time()

            # ─── OpenCV 表示 ───
            color_image          = np.asanyarray(color_frame.get_data())
            depth_colormap, depth_m = depth_to_colormap(depth_frame)

            # 中央の深度距離をオーバーレイ
            cy, cx    = depth_m.shape[0] // 2, depth_m.shape[1] // 2
            center_d  = depth_m[cy, cx]
            cv2.circle(color_image, (cx, cy), 6, (0, 255, 0), 2)
            cv2.putText(color_image,
                        f"{center_d:.2f} m" if center_d > 0 else "---",
                        (cx + 10, cy - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(color_image,
                        f"FPS: {displayed_fps:.1f}",
                        (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 0), 2)
            cv2.putText(color_image, "[S] Save PLY  [D] Save Depth  [Q] Quit",
                        (10, color_image.shape[0] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

            combined = np.hstack([color_image, depth_colormap])
            cv2.imshow("RealSense D435 | Color + Depth", combined)

            # ─── Open3D 点群更新 ───
            if viz and HAS_OPEN3D:
                pcd = frames_to_pointcloud(depth_frame, color_frame, pc_calc)
                pcd_vis.points = pcd.points
                pcd_vis.colors = pcd.colors
                viz.update_geometry(pcd_vis)
                viz.poll_events()
                viz.update_renderer()

            # ─── キー入力 ───
            key = cv2.waitKey(1) & 0xFF

            if key in (ord('q'), 27):   # Q / ESC
                break

            elif key == ord('s'):       # 点群保存
                if HAS_OPEN3D:
                    pcd  = frames_to_pointcloud(depth_frame, color_frame, pc_calc)
                    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
                    path = output_dir / f"pointcloud_{ts}_{save_count:04d}.ply"
                    o3d.io.write_point_cloud(str(path), pcd)
                    save_count += 1
                    print(f"[SAVED] {path}  ({len(pcd.points):,} points)")
                else:
                    print("[WARN] open3d が無いため .ply 保存をスキップしました")

            elif key == ord('d'):       # 深度 PNG 保存
                ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
                depth_path  = output_dir / f"depth_{ts}.png"
                color_path  = output_dir / f"color_{ts}.png"
                depth_raw   = np.asanyarray(depth_frame.get_data())   # uint16
                cv2.imwrite(str(depth_path), depth_raw)
                cv2.imwrite(str(color_path), color_image)
                print(f"[SAVED] {depth_path} / {color_path}")

    except KeyboardInterrupt:
        print("\n[INFO] 中断されました")
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()
        if viz:
            viz.destroy_window()
        print("[INFO] パイプライン停止")


# ─────────────────────────────────────────────
#  エントリポイント
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="RealSense D435 空間マップ生成",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("-m", "--mode",    choices=["live", "record", "playback"],
                   default="live",   help="動作モード (デフォルト: live)")
    p.add_argument("-o", "--output",  default="./output",
                                      help="出力ディレクトリ (デフォルト: ./output)")
    p.add_argument("-b", "--bag",     default=None,
                                      help=".bag ファイルパス (playback 時に必須)")
    p.add_argument("--no-viz",        action="store_true",
                                      help="Open3D リアルタイム可視化を無効化")
    p.add_argument("--fps",           type=int, default=30,
                                      help="フレームレート (デフォルト: 30)")
    p.add_argument("--width",         type=int, default=848,
                                      help="ストリーム幅 (デフォルト: 848)")
    p.add_argument("--height",        type=int, default=480,
                                      help="ストリーム高さ (デフォルト: 480)")
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())