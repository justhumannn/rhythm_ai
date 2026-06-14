#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web_app.bpm import analyze_bpm


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze BPM and confidence.")
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--title")
    parser.add_argument("--min-bpm", type=float, default=60.0)
    parser.add_argument("--max-bpm", type=float, default=360.0)
    args = parser.parse_args()

    analysis = analyze_bpm(
        args.audio,
        title=args.title,
        min_bpm=args.min_bpm,
        max_bpm=args.max_bpm,
    )
    print(json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
