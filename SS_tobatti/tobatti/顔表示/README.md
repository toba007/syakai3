# Face GIF Animator

OpenCVで顔を描画し、ランダムな瞬きと口パクを付けたGIFを作成します。
`face_app.py` を使うと、デスクトップアプリとして画面上でアニメーションを再生できます。

## セットアップ

Windows:

```powershell
py -m pip install -r requirements.txt
```

Raspberry Pi:

```bash
sudo apt update
sudo apt install -y python3-tk python3-opencv python3-pil python3-pil.imagetk
```

## デスクトップアプリとして実行

Windows:

```powershell
py face_app.py
```

Raspberry Pi:

```bash
python3 face_app.py
```

アプリでは顔アニメーションを常時再生できます。
`再生 / 停止` で一時停止、`リセット` で動きを作り直し、`GIF保存` でGIFを書き出します。
起動時は全画面表示です。`Esc` で全画面解除、`F11` で全画面切り替えができます。
`a` を押すと怒った顔、`b` を押すと悲しい顔を3秒間表示します。
瞬きは表情表示中もランダムに動き続けます。
画面をタップまたはクリックしている間だけ、モニター中心から見たタップ方向へ黒目が向きます。

Windowsでは `run_face_app.bat` をダブルクリックして起動できます。
このPCのデスクトップには `Face Animation` ショートカットを作成済みです。

Raspberry Piでデスクトップアイコンを作る場合は、`face-animation.desktop` の `Path` を設置先フォルダに合わせてから、デスクトップへコピーします。

```bash
cp face-animation.desktop ~/Desktop/
chmod +x ~/Desktop/face-animation.desktop
```

## GIFだけ作成

Windows:

```powershell
py animate_face.py
```

Raspberry Pi:

```bash
python3 animate_face.py
```

出力先:

```text
output/face_animation.gif
```

同じ動きを再現したい場合は `--seed` を指定します。

```powershell
py animate_face.py --seed 10 --seconds 8 --fps 12
```

## 調整する場所

- 瞬きの間隔: `RandomFaceAnimator._next_blink_frame`
- 左右の瞬きが同時に起きる確率: `state_for_frame` 内の `0.72`
- 瞬きの長さ: `state_for_frame` 内の `self.random.randint(2, 4)`
- 口の種類と出やすさ: `_choose_mouth`
- 口の切り替え間隔: `state_for_frame` 内の `self.random.randint(8, 22)`
