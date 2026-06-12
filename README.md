# 社会実装プロジェクト: コミュニケーションロボット

## 構成

- `SS_tobatti/tobatti/robot_controller.py`: Windows側の統合ランナー
- `SS_tobatti/tobatti/face-ui/`: 顔アニメーション
- `SS_tobatti/tobatti/weather_report/`: OpenWeatherMapの天気読み上げ文生成
- `SS_tobatti/tobatti/news_report/`: NewsAPIまたはNHK RSSのニュース読み上げ文生成
- `SS_tobatti/tobatti/clock_report/`: 時刻読み上げ文生成

## セットアップ

```powershell
cd SS_tobatti\tobatti
py -m pip install -r requirements.txt
```

RealSense D435はPythonパッケージ `pyrealsense2` を使います。認識コードは `robot_controller.py` の `RealSensePresenceDetector` に入っています。

## 環境変数

`SS_tobatti/tobatti/config.txt` にAPIキーを保存できます。

```text
GEMINI_API_KEY=GeminiのAPIキー
OPENWEATHER_API_KEY=OpenWeatherMapのAPIキー
NEWS_API_KEY=NewsAPIのAPIキー
ESP32_PORT=COM3
GEMINI_MODEL=gemini-1.5-flash
```

PowerShellで一時的に指定する場合:

```powershell
$env:GEMINI_API_KEY="GeminiのAPIキー"
$env:OPENWEATHER_API_KEY="OpenWeatherMapのAPIキー"
$env:NEWS_API_KEY="NewsAPIのAPIキー"
$env:ESP32_PORT="COM3"
```

`NEWS_API_KEY`は未設定でもNHK RSSへフォールバックします。

## 実行

顔UIを常時表示しながら、制御プログラムを並行起動する場合:

```powershell
SS_tobatti\tobatti\run_robot_controller.bat
```

このbatはPython 3.11を優先して使い、必要なPythonパッケージが無い場合は `requirements.txt` からインストールします。RealSense D435を使う場合、Python 3.14では `pyrealsense2` が入らないため、Python 3.11をインストールしてから実行してください。

## ROS2版

ROS2で検知・会話・読み上げ・モーションを別ノードに分けた構成も追加しています。

- `ros2_ws/src/tobatti_robot/tobatti_robot/presence_node.py`: RealSense D435で人検知し、`person_present` を publish
- `dialogue_node.py`: Gemini、マイク聞き取り、不在時の天気/ニュース/豆知識/雑談を制御
- `speaker_node.py`: `speech_text` を購読して読み上げ
- `motion_node.py`: `motion_command` を購読してESP32へモーション送信

ROS2が入っている環境では以下を実行します。

```powershell
run_ros2_robot.bat
```

ROS2がPATHに無い場合は、`SS_tobatti/tobatti/config.txt` に `local_setup.bat` の場所を指定します。

```text
ROS2_SETUP_BAT=C:\dev\ros2_jazzy\local_setup.bat
```

このPCでは `ros2` と `colcon` がPATHに見つからなかったため、ROS2ビルド実行までは未検証です。

ESP32とRealSenseを使う通常起動:

```powershell
py robot_controller.py --esp32-port COM3
```

RealSenseなしで会話だけ動作確認:

```powershell
py robot_controller.py --text-chat
```

ESP32側は、Windowsから送られるモーション名を1行単位で受け取り、対応するサーボモーションを再生する想定です。初期値では `nod,wave,happy,think,idle` のいずれかを送ります。

発話中は、読み上げ処理とは別スレッドでランダムモーションを送り続けます。間隔は `--motion-interval 1.8` のように変更できます。
