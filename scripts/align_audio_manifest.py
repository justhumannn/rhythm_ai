#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rhythm_ai.alignment import (
    audio_onset_strength,
    detect_gameplay_mode,
    estimate_chart_audio_offset,
    has_constant_bpm,
    summarize_alignment,
)
from rhythm_ai.chart import load_jsonl, normalize_title


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Estimate chart/audio offsets and mark usable 4B training audio."
    )
    parser.add_argument("--charts", default="data/djmax_4b_charts.jsonl")
    parser.add_argument("--manifest", default="data/audio_manifest.json", type=Path)
    parser.add_argument(
        "--output",
        default="data/audio_manifest_aligned.json",
        type=Path,
    )
    parser.add_argument("--max-offset-seconds", type=float, default=5.0)
    parser.add_argument("--min-alignment-score", type=float, default=0.2)
    parser.add_argument("--max-alignment-spread", type=float, default=0.15)
    args = parser.parse_args()

    charts_by_title: dict[str, list[dict]] = defaultdict(list)
    for chart in load_jsonl(args.charts):
        charts_by_title[normalize_title(chart["title"])].append(chart)

    rows = json.loads(args.manifest.read_text(encoding="utf-8"))
    output_rows: list[dict] = []
    eligible_count = 0
    reason_counts: dict[str, int] = defaultdict(int)

    for index, source_row in enumerate(rows, start=1):
        row = dict(source_row)
        charts = charts_by_title.get(normalize_title(row["title"]), [])
        constant_charts = [chart for chart in charts if has_constant_bpm(chart)]
        source_mode = detect_gameplay_mode(row["audio_path"])
        row["source_gameplay_mode"] = source_mode

        reasons: list[str] = []
        if charts and not constant_charts:
            reasons.append("variable_bpm_without_timing_map")
        if source_mode is not None and source_mode != "4B":
            reasons.append(f"gameplay_mode_mismatch:{source_mode}")

        if constant_charts:
            onset_strength, frame_seconds = audio_onset_strength(row["audio_path"])
            results = [
                estimate_chart_audio_offset(
                    chart,
                    onset_strength,
                    frame_seconds=frame_seconds,
                    max_offset_seconds=args.max_offset_seconds,
                )
                for chart in constant_charts
            ]
            row.update(summarize_alignment(results))
            if row["alignment_score"] < args.min_alignment_score:
                reasons.append("low_alignment_score")
            if row["alignment_spread_seconds"] > args.max_alignment_spread:
                reasons.append("inconsistent_difficulty_alignment")
            if (
                abs(row["audio_offset_seconds"])
                >= args.max_offset_seconds - frame_seconds
            ):
                reasons.append("alignment_at_search_boundary")
        else:
            row.update(
                {
                    "audio_offset_seconds": 0.0,
                    "alignment_score": 0.0,
                    "alignment_margin": 0.0,
                    "alignment_spread_seconds": 0.0,
                }
            )

        row["training_eligible"] = not reasons
        row["training_exclusion_reasons"] = reasons
        if row["training_eligible"]:
            eligible_count += 1
        for reason in reasons:
            reason_counts[reason.split(":", 1)[0]] += 1
        output_rows.append(row)
        print(
            f"[{index}/{len(rows)}] {row['title']}: "
            f"offset={row['audio_offset_seconds']:+.3f}s "
            f"score={row['alignment_score']:.3f} "
            f"eligible={row['training_eligible']}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output_rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"eligible: {eligible_count}/{len(output_rows)}")
    print(f"excluded: {dict(sorted(reason_counts.items()))}")
    print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
