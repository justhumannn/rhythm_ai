#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rhythm_ai.chart import load_jsonl, normalize_title
from rhythm_ai.matching import best_chart_match


AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}


def find_audio_files(audio_dir: Path) -> list[Path]:
    return [
        path
        for path in audio_dir.rglob("*")
        if path.is_file() and path.suffix.casefold() in AUDIO_EXTENSIONS
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a chart-title to local-audio manifest."
    )
    parser.add_argument("--charts", default="data/djmax_4b_charts.jsonl")
    parser.add_argument("--audio-dir", required=True, type=Path)
    parser.add_argument("--output", default="data/audio_manifest.json", type=Path)
    parser.add_argument(
        "--missing-output",
        default="data/missing_audio_queries.txt",
        type=Path,
    )
    args = parser.parse_args()

    charts = load_jsonl(args.charts)
    audio_files = find_audio_files(args.audio_dir)

    rows_by_title: dict[str, dict] = {}
    unmatched_audio = []
    for audio_path in audio_files:
        match = best_chart_match(audio_path, charts)
        if match is None:
            unmatched_audio.append(str(audio_path))
            continue
        title = match.chart["title"]
        current = rows_by_title.get(title)
        row = {
            "title": title,
            "audio_path": str(audio_path),
            "matched_mode": match.chart["mode"],
            "matched_difficulty": match.chart["difficulty"],
            "match_score": match.score,
        }
        if current is None or row["match_score"] > current["match_score"]:
            rows_by_title[title] = row

    rows = sorted(rows_by_title.values(), key=lambda row: normalize_title(row["title"]))
    matched_titles = {row["title"] for row in rows}
    missing_queries = [
        f"DJMAX RESPECT V {title}"
        for title in sorted({chart["title"] for chart in charts}, key=str.casefold)
        if title not in matched_titles
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.missing_output.parent.mkdir(parents=True, exist_ok=True)
    args.missing_output.write_text("\n".join(missing_queries) + "\n", encoding="utf-8")

    print(f"matched: {len(rows)}")
    print(f"missing: {len(missing_queries)}")
    print(f"unmatched audio: {len(unmatched_audio)}")
    print(f"manifest: {args.output}")
    print(f"missing queries: {args.missing_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
