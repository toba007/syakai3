import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PREVIEW_HTML = r"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Motion Preview</title>
  <style>
    :root {
      color-scheme: light;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: #eef2f6;
      color: #22313f;
    }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    header {
      padding: 18px 24px;
      background: #ffffff;
      border-bottom: 1px solid #cfd7df;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1 {
      font-size: 22px;
      margin: 0;
      letter-spacing: 0;
    }
    .status {
      font-size: 18px;
      font-weight: 700;
      color: #0f6b5f;
    }
    main {
      display: grid;
      place-items: center;
      padding: 28px;
    }
    .stage {
      width: min(820px, 94vw);
      height: min(560px, 72vh);
      min-height: 420px;
      position: relative;
      overflow: hidden;
      background: linear-gradient(#f8fbfd 0 72%, #d9e4ec 72% 100%);
      border: 1px solid #bfccd7;
      border-radius: 8px;
    }
    .floor {
      position: absolute;
      left: 7%;
      right: 7%;
      bottom: 22%;
      height: 3px;
      background: #93a4b3;
    }
    .robot {
      position: absolute;
      left: calc(50% - 70px);
      bottom: 22%;
      width: 140px;
      height: 260px;
      transform-origin: 50% 100%;
      transition: filter 160ms ease;
    }
    .part {
      position: absolute;
      box-sizing: border-box;
      border: 3px solid #263849;
      background: #f5f7fa;
    }
    .head {
      left: 40px;
      top: 0;
      width: 60px;
      height: 54px;
      border-radius: 8px;
      background: #ffd166;
    }
    .eye {
      position: absolute;
      top: 20px;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #263849;
    }
    .eye.left { left: 15px; }
    .eye.right { right: 15px; }
    .body {
      left: 32px;
      top: 66px;
      width: 76px;
      height: 88px;
      border-radius: 8px;
      background: #3d8bfd;
    }
    .arm, .leg {
      transform-origin: 50% 0;
      border-radius: 999px;
    }
    .arm {
      top: 74px;
      width: 22px;
      height: 90px;
      background: #5aa3ff;
    }
    .arm.left { left: 8px; }
    .arm.right { right: 8px; }
    .leg {
      top: 150px;
      width: 24px;
      height: 100px;
      background: #26a269;
    }
    .leg.left { left: 42px; }
    .leg.right { right: 42px; }
    .label {
      position: absolute;
      left: 24px;
      bottom: 20px;
      font-size: 22px;
      font-weight: 800;
      color: #263849;
    }
    .hint {
      position: absolute;
      right: 24px;
      bottom: 22px;
      font-size: 16px;
      color: #526170;
    }
    .play.motion1 .robot { animation: idle 900ms infinite ease-in-out; }
    .play.motion2 .robot { animation: walkForward 850ms infinite ease-in-out; }
    .play.motion3 .robot { animation: walkBackward 850ms infinite ease-in-out; }
    .play.motion4 .robot { animation: turnLeft 900ms infinite ease-in-out; }
    .play.motion5 .robot { animation: turnRight 900ms infinite ease-in-out; }
    .play.motion6 .robot { animation: sideLeft 900ms infinite ease-in-out; }
    .play.motion7 .robot { animation: sideRight 900ms infinite ease-in-out; }
    .play.motion8 .arm.right { animation: wave 520ms infinite ease-in-out; }
    .play.motion9 .robot { animation: bow 900ms infinite ease-in-out; }
    .play.motion10 .robot { animation: squat 900ms infinite ease-in-out; }
    .play.motion11 .leg.left { animation: kickLeft 760ms infinite ease-in-out; }
    .play.motion12 .robot { animation: dance 720ms infinite ease-in-out; }
    .queue .robot { filter: saturate(0.72); }
    @keyframes idle { 50% { transform: translateY(-8px); } }
    @keyframes walkForward { 50% { transform: translateX(90px) translateY(-8px); } }
    @keyframes walkBackward { 50% { transform: translateX(-90px) translateY(-8px); } }
    @keyframes turnLeft { 50% { transform: rotate(-16deg) translateX(-20px); } }
    @keyframes turnRight { 50% { transform: rotate(16deg) translateX(20px); } }
    @keyframes sideLeft { 50% { transform: translateX(-110px); } }
    @keyframes sideRight { 50% { transform: translateX(110px); } }
    @keyframes wave { 50% { transform: rotate(-115deg); } }
    @keyframes bow { 50% { transform: rotate(18deg) translateY(18px); } }
    @keyframes squat { 50% { transform: translateY(42px) scaleY(.82); } }
    @keyframes kickLeft { 50% { transform: rotate(70deg); } }
    @keyframes dance {
      25% { transform: translateX(-45px) rotate(-8deg); }
      50% { transform: translateY(-24px); }
      75% { transform: translateX(45px) rotate(8deg); }
    }
  </style>
</head>
<body>
  <header>
    <h1>Motion Preview</h1>
    <div id="status" class="status">waiting</div>
  </header>
  <main>
    <section id="stage" class="stage play motion1">
      <div class="floor"></div>
      <div class="robot" aria-label="robot preview">
        <div class="part head"><span class="eye left"></span><span class="eye right"></span></div>
        <div class="part body"></div>
        <div class="part arm left"></div>
        <div class="part arm right"></div>
        <div class="part leg left"></div>
        <div class="part leg right"></div>
      </div>
      <div id="label" class="label">motion1</div>
      <div class="hint">Controlled by the Tkinter GUI</div>
    </section>
  </main>
  <script>
    const stage = document.getElementById("stage");
    const label = document.getElementById("label");
    const status = document.getElementById("status");

    async function refresh() {
      try {
        const response = await fetch("/state", { cache: "no-store" });
        const state = await response.json();
        const motion = state.motion || "motion1";
        const mode = (state.mode || "PLAY").toLowerCase();
        stage.className = `stage ${state.running ? "play" : "stopped"} ${mode} ${motion}`;
        label.textContent = motion;
        status.textContent = state.running ? `${state.mode} ${motion}` : `stopped: ${motion}`;
      } catch (_error) {
        status.textContent = "preview server disconnected";
      }
    }

    refresh();
    setInterval(refresh, 250);
  </script>
</body>
</html>
"""


class WebMotionPreview:
    def __init__(self, host="127.0.0.1", port=8765):
        self.host = host
        self.port = port
        self.httpd = None
        self.thread = None
        self.lock = threading.Lock()
        self.state = {"motion": "motion1", "mode": "PLAY", "running": True}

    @property
    def url(self):
        return f"http://{self.host}:{self.port}/"

    def start(self):
        preview = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/" or self.path.startswith("/index"):
                    body = PREVIEW_HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path.startswith("/state"):
                    with preview.lock:
                        body = json.dumps(preview.state).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_error(404)

            def log_message(self, _format, *_args):
                return

        for offset in range(10):
            try:
                self.port = self.port + offset
                self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
                break
            except OSError:
                self.port = 8765
        if self.httpd is None:
            raise RuntimeError("Could not start web preview server.")

        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def set_motion(self, motion, mode):
        with self.lock:
            self.state = {"motion": motion, "mode": mode, "running": True}

    def stop(self):
        with self.lock:
            self.state = {**self.state, "running": False}

    def clear(self):
        with self.lock:
            self.state = {"motion": "motion1", "mode": "CLEAR", "running": False}

    def shutdown(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
