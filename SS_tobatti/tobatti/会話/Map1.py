"""
点群マージ & ボクセルダウンサンプリング ユーティリティ
=====================================================
複数フレームの .ply 点群を ICP で位置合わせして結合し、
ボクセルグリッドで間引いた「空間マップ」を生成する。

依存: open3d, numpy

使い方:
    python merge_pointclouds.py -i ./output -o map.ply --voxel 0.02
"""

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import open3d as o3d
except ImportError:
    sys.exit("[ERROR] open3d が必要です。  pip install open3d")


def load_ply_files(input_dir: Path) -> list:
    files = sorted(input_dir.glob("*.ply"))
    if not files:
        sys.exit(f"[ERROR] .ply ファイルが見つかりません: {input_dir}")
    print(f"[INFO] {len(files)} 個の .ply ファイルを読み込みます")
    return [o3d.io.read_point_cloud(str(f)) for f in files]


def preprocess(pcd, voxel_size: float):
    """ダウンサンプル + 法線推定 + FPFH 特徴量"""
    pcd_down = pcd.voxel_down_sample(voxel_size)
    pcd_down.estimate_normals(
        o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_size * 2, max_nn=30)
    )
    fpfh = o3d.pipelines.registration.compute_fpfh_feature(
        pcd_down,
        o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_size * 5, max_nn=100),
    )
    return pcd_down, fpfh


def global_registration(src_down, tgt_down, src_fpfh, tgt_fpfh, voxel_size):
    """RANSAC によるグローバル位置合わせ"""
    dist_thr = voxel_size * 1.5
    result = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
        src_down, tgt_down, src_fpfh, tgt_fpfh,
        mutual_filter=True,
        max_correspondence_distance=dist_thr,
        estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
        ransac_n=4,
        checkers=[
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(dist_thr),
        ],
        criteria=o3d.pipelines.registration.RANSACConvergenceCriteria(4_000_000, 500),
    )
    return result.transformation


def icp_refine(src, tgt, init_transform, voxel_size):
    """ICP による精密位置合わせ"""
    result = o3d.pipelines.registration.registration_icp(
        src, tgt,
        max_correspondence_distance=voxel_size * 0.4,
        init=init_transform,
        estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPlane(),
    )
    return result.transformation


def merge_clouds(clouds: list, voxel_size: float) -> o3d.geometry.PointCloud:
    """全フレームを順次 ICP でアライメントして結合"""
    merged = clouds[0]
    T_accum = np.eye(4)

    for i, src in enumerate(clouds[1:], start=1):
        print(f"  フレーム {i}/{len(clouds)-1} を位置合わせ中 ...", end=" ", flush=True)
        tgt = merged

        src_down, src_fpfh = preprocess(src,    voxel_size)
        tgt_down, tgt_fpfh = preprocess(merged, voxel_size)

        T_init  = global_registration(src_down, tgt_down, src_fpfh, tgt_fpfh, voxel_size)
        T_final = icp_refine(src_down, tgt_down, T_init, voxel_size)
        T_accum = T_final @ T_accum

        src_aligned = src.transform(T_final)
        merged      = merged + src_aligned
        merged      = merged.voxel_down_sample(voxel_size)
        print("完了")

    return merged


def main(args):
    input_dir  = Path(args.input)
    output_ply = Path(args.output)
    voxel_size = args.voxel

    clouds = load_ply_files(input_dir)

    print(f"[INFO] 位置合わせ & マージ開始 (voxel={voxel_size} m)")
    merged = merge_clouds(clouds, voxel_size)

    # 最終ダウンサンプリング
    final = merged.voxel_down_sample(voxel_size)
    # 外れ値除去
    final, _ = final.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
    # 法線推定（任意）
    final.estimate_normals(
        o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_size * 2, max_nn=30)
    )

    output_ply.parent.mkdir(parents=True, exist_ok=True)
    o3d.io.write_point_cloud(str(output_ply), final)
    print(f"\n[SAVED] {output_ply}  ({len(final.points):,} points)")

    # 可視化
    print("[INFO] 点群を表示します (ウィンドウを閉じると終了)")
    o3d.visualization.draw_geometries(
        [final],
        window_name="空間マップ",
        width=1280,
        height=720,
        point_show_normal=False,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="点群マージ & 空間マップ生成")
    p.add_argument("-i", "--input",  default="./output",   help="入力 .ply ディレクトリ")
    p.add_argument("-o", "--output", default="./map.ply",  help="出力 .ply ファイルパス")
    p.add_argument("--voxel",        type=float, default=0.02,
                   help="ボクセルサイズ [m] (デフォルト: 0.02)")
    main(p.parse_args())