from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REAL_SCRIPT = Path(__file__).resolve().parents[1] / "news_report" / "fetch_japan_news.py"
SPEC = importlib.util.spec_from_file_location("news_report_fetch_japan_news", REAL_SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load news module: {REAL_SCRIPT}")

MODULE = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("news_report_fetch_japan_news", MODULE)
SPEC.loader.exec_module(MODULE)

fetch_japan_news = MODULE.fetch_japan_news
build_arg_parser = MODULE.build_arg_parser
main = MODULE.main


if __name__ == "__main__":
    raise SystemExit(main())
