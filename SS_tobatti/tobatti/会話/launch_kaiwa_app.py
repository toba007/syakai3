import runpy
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def main():
    candidates = [
        path
        for path in BASE_DIR.glob("*.py")
        if path.name not in {"launch_kaiwa_app.py", "ElevenLabs_test.py"}
    ]
    if not candidates:
        raise SystemExit("No conversation app Python file was found.")

    target = max(candidates, key=lambda path: path.stat().st_size)
    print(f"[launcher] Starting: {target.name}")
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
