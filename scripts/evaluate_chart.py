#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rhythm_ai.chart import LANES_4B, bpm_for_chart, normalize_title


def load_chart(path: Path) -> dict:
    if path.suffix == ".jsonl":
        raise ValueError("use --charts-jsonl for JSONL files")
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def event_beat(event: dict) -> float:
    return float(event["beat"])


def event_end_beat(event: dict) -> float:
    return float(event.get("endBeat", event["beat"]))


def chart_duration_beats(chart: dict) -> float:
    events = chart.get("events", [])
    if not events:
        return 0.0
    return max(event_end_beat(event) for event in events)


def chart_duration_seconds(chart: dict) -> float:
    playtime = chart.get("playtimeSeconds")
    if playtime:
        return float(playtime)
    bpm = bpm_for_chart(chart)
    return chart_duration_beats(chart) * 60.0 / bpm


def bucket(value: float, size: float) -> float:
    return math.floor(value / size) * size


def evaluate_chart(chart: dict, *, window_beats: float = 4.0) -> dict:
    events = sorted(chart.get("events", []), key=event_beat)
    taps = [event for event in events if event["type"] == "tap"]
    holds = [event for event in events if event["type"] == "hold"]
    duration_beats = chart_duration_beats(chart)
    duration_seconds = chart_duration_seconds(chart)
    bpm = bpm_for_chart(chart)

    lane_counts = Counter(str(event["lane"]) for event in events)
    beat_counts = Counter(round(event_beat(event), 6) for event in events)
    chord_counts = Counter(count for count in beat_counts.values() if count >= 2)
    intervals = [
        event_beat(curr) - event_beat(prev)
        for prev, curr in zip(events, events[1:])
        if event_beat(curr) >= event_beat(prev)
    ]
    density_windows = density_by_window(events, duration_beats, window_beats)

    return {
        "title": chart.get("title"),
        "mode": chart.get("mode"),
        "difficulty": chart.get("difficulty"),
        "bpm": bpm,
        "durationBeats": round(duration_beats, 6),
        "durationSeconds": round(duration_seconds, 6),
        "noteCount": len(events),
        "tapCount": len(taps),
        "holdCount": len(holds),
        "notesPerSecond": safe_div(len(events), duration_seconds),
        "notesPerBeat": safe_div(len(events), duration_beats),
        "holdRatio": safe_div(len(holds), len(events)),
        "laneCounts": {lane: lane_counts.get(lane, 0) for lane in LANES_4B},
        "laneRatios": {
            lane: round(safe_div(lane_counts.get(lane, 0), len(events)), 6)
            for lane in LANES_4B
        },
        "chordStats": {
            "chordEventCount": sum(chord_counts.values()),
            "maxChordSize": max(beat_counts.values(), default=0),
            "bySize": {str(size): count for size, count in sorted(chord_counts.items())},
        },
        "intervalStats": summarize_numbers(intervals),
        "density": {
            "windowBeats": window_beats,
            "mean": round(statistics.mean(density_windows), 6) if density_windows else 0.0,
            "max": max(density_windows, default=0),
            "p95": percentile(density_windows, 0.95),
            "topWindows": top_density_windows(events, window_beats, limit=8),
        },
        "warnings": warnings_for_chart(events, lane_counts, density_windows),
    }


def density_by_window(events: list[dict], duration_beats: float, window_beats: float) -> list[int]:
    if duration_beats <= 0:
        return []
    window_count = max(1, math.ceil(duration_beats / window_beats))
    counts = [0 for _ in range(window_count)]
    for event in events:
        index = min(window_count - 1, int(event_beat(event) // window_beats))
        counts[index] += 1
    return counts


def top_density_windows(events: list[dict], window_beats: float, *, limit: int) -> list[dict]:
    counts: dict[float, int] = defaultdict(int)
    for event in events:
        start = bucket(event_beat(event), window_beats)
        counts[start] += 1
    return [
        {"startBeat": round(start, 6), "endBeat": round(start + window_beats, 6), "notes": count}
        for start, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def summarize_numbers(values: list[float]) -> dict:
    if not values:
        return {"min": 0.0, "mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}
    return {
        "min": round(min(values), 6),
        "mean": round(statistics.mean(values), 6),
        "median": round(statistics.median(values), 6),
        "p10": percentile(values, 0.10),
        "p90": percentile(values, 0.90),
    }


def percentile(values: list[float] | list[int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return round(float(ordered[index]), 6)


def safe_div(a: float, b: float) -> float:
    return round(a / b, 6) if b else 0.0


def warnings_for_chart(
    events: list[dict],
    lane_counts: Counter,
    density_windows: list[int],
) -> list[str]:
    warnings: list[str] = []
    if not events:
        warnings.append("no events")
        return warnings

    total = len(events)
    for lane in LANES_4B:
        ratio = lane_counts.get(lane, 0) / total
        if ratio < 0.10:
            warnings.append(f"lane {lane} is underused ({ratio:.1%})")
        if ratio > 0.40:
            warnings.append(f"lane {lane} is overused ({ratio:.1%})")

    max_density = max(density_windows, default=0)
    mean_density = statistics.mean(density_windows) if density_windows else 0
    if mean_density and max_density > mean_density * 2.5:
        warnings.append(
            f"density spike: max window {max_density} notes vs mean {mean_density:.2f}"
        )
    return warnings


def compare_metrics(
    candidate: dict,
    reference: dict,
    *,
    candidate_chart: dict | None = None,
    reference_chart: dict | None = None,
    timing_tolerance_beats: float = 0.125,
) -> dict:
    comparable = [
        "noteCount",
        "tapCount",
        "holdCount",
        "notesPerSecond",
        "notesPerBeat",
        "holdRatio",
    ]
    diff = {}
    for key in comparable:
        candidate_value = candidate[key]
        reference_value = reference[key]
        diff[key] = {
            "candidate": candidate_value,
            "reference": reference_value,
            "delta": round(candidate_value - reference_value, 6),
            "ratio": safe_div(candidate_value, reference_value),
        }

    lane_delta = {}
    for lane in LANES_4B:
        lane_delta[lane] = round(
            candidate["laneRatios"][lane] - reference["laneRatios"][lane], 6
        )
    diff["laneRatioDelta"] = lane_delta
    if candidate_chart is not None and reference_chart is not None:
        diff["timingMatch"] = compare_event_timing(
            candidate_chart,
            reference_chart,
            tolerance_beats=timing_tolerance_beats,
        )
    return diff


def compare_event_timing(
    candidate: dict,
    reference: dict,
    *,
    tolerance_beats: float,
) -> dict:
    return {
        "toleranceBeats": tolerance_beats,
        "all": match_events(
            candidate.get("events", []),
            reference.get("events", []),
            tolerance_beats=tolerance_beats,
        ),
        "tap": match_events(
            [
                event
                for event in candidate.get("events", [])
                if event["type"] == "tap"
            ],
            [
                event
                for event in reference.get("events", [])
                if event["type"] == "tap"
            ],
            tolerance_beats=tolerance_beats,
        ),
        "hold": match_events(
            [
                event
                for event in candidate.get("events", [])
                if event["type"] == "hold"
            ],
            [
                event
                for event in reference.get("events", [])
                if event["type"] == "hold"
            ],
            tolerance_beats=tolerance_beats,
        ),
    }


def match_events(
    candidate_events: list[dict],
    reference_events: list[dict],
    *,
    tolerance_beats: float,
) -> dict:
    true_positive = 0
    absolute_errors: list[float] = []

    for lane in LANES_4B:
        candidate_beats = sorted(
            float(event["beat"])
            for event in candidate_events
            if str(event["lane"]) == lane
        )
        reference_beats = sorted(
            float(event["beat"])
            for event in reference_events
            if str(event["lane"]) == lane
        )
        candidate_index = 0
        reference_index = 0
        while (
            candidate_index < len(candidate_beats)
            and reference_index < len(reference_beats)
        ):
            candidate_beat = candidate_beats[candidate_index]
            reference_beat = reference_beats[reference_index]
            error = candidate_beat - reference_beat
            if abs(error) <= tolerance_beats:
                true_positive += 1
                absolute_errors.append(abs(error))
                candidate_index += 1
                reference_index += 1
            elif candidate_beat < reference_beat:
                candidate_index += 1
            else:
                reference_index += 1

    false_positive = len(candidate_events) - true_positive
    false_negative = len(reference_events) - true_positive
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    return {
        "matched": true_positive,
        "falsePositive": false_positive,
        "falseNegative": false_negative,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "meanAbsoluteBeatError": (
            round(statistics.mean(absolute_errors), 6)
            if absolute_errors
            else None
        ),
    }


def find_reference(charts: list[dict], title: str, difficulty: str | None) -> dict | None:
    key = normalize_title(title)
    candidates = [chart for chart in charts if normalize_title(chart["title"]) == key]
    if difficulty:
        candidates = [chart for chart in candidates if chart.get("difficulty") == difficulty]
    return candidates[0] if candidates else None


def print_human_report(metrics: dict, comparison: dict | None) -> None:
    print(f"{metrics['title']} {metrics['mode']} {metrics['difficulty']}")
    print(
        f"notes={metrics['noteCount']} taps={metrics['tapCount']} holds={metrics['holdCount']} "
        f"nps={metrics['notesPerSecond']} npb={metrics['notesPerBeat']}"
    )
    print(f"duration={metrics['durationSeconds']}s / {metrics['durationBeats']} beats bpm={metrics['bpm']}")
    print(f"lanes={metrics['laneCounts']}")
    print(f"chords={metrics['chordStats']}")
    print(f"density={metrics['density']}")
    if metrics["warnings"]:
        print("warnings:")
        for warning in metrics["warnings"]:
            print(f"- {warning}")
    if comparison:
        print("comparison:")
        for key, value in comparison.items():
            print(f"- {key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate rhythm chart statistics.")
    parser.add_argument("--chart", type=Path, help="single generated/original chart JSON")
    parser.add_argument("--charts-jsonl", type=Path, help="evaluate every chart in a JSONL file")
    parser.add_argument("--reference-jsonl", type=Path, default=Path("data/djmax_4b_charts.jsonl"))
    parser.add_argument("--reference-title")
    parser.add_argument("--reference-difficulty")
    parser.add_argument("--timing-tolerance-beats", type=float, default=0.125)
    parser.add_argument("--window-beats", type=float, default=4.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    if not args.chart and not args.charts_jsonl:
        parser.error("provide --chart or --charts-jsonl")

    if args.chart:
        chart = load_chart(args.chart)
        metrics = evaluate_chart(chart, window_beats=args.window_beats)
        comparison = None
        if args.reference_title:
            reference_charts = load_jsonl(args.reference_jsonl)
            reference_chart = find_reference(
                reference_charts,
                args.reference_title,
                args.reference_difficulty,
            )
            if reference_chart is None:
                raise SystemExit("reference chart not found")
            comparison = compare_metrics(
                metrics,
                evaluate_chart(reference_chart, window_beats=args.window_beats),
                candidate_chart=chart,
                reference_chart=reference_chart,
                timing_tolerance_beats=args.timing_tolerance_beats,
            )
        payload = {"metrics": metrics, "comparison": comparison}
    else:
        charts = load_jsonl(args.charts_jsonl)
        metrics_list = [evaluate_chart(chart, window_beats=args.window_beats) for chart in charts]
        payload = {
            "chartCount": len(metrics_list),
            "summary": summarize_dataset(metrics_list),
            "charts": metrics_list,
        }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.chart:
        print_human_report(payload["metrics"], payload["comparison"])
    else:
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


def summarize_dataset(metrics_list: list[dict]) -> dict:
    return {
        "chartCount": len(metrics_list),
        "noteCount": summarize_numbers([item["noteCount"] for item in metrics_list]),
        "notesPerSecond": summarize_numbers([item["notesPerSecond"] for item in metrics_list]),
        "holdRatio": summarize_numbers([item["holdRatio"] for item in metrics_list]),
        "maxDensity": summarize_numbers([item["density"]["max"] for item in metrics_list]),
    }


if __name__ == "__main__":
    raise SystemExit(main())
