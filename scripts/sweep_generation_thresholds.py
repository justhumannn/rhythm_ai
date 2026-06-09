#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from itertools import product
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rhythm_ai.audio import audio_to_features
from rhythm_ai.chart import DIFFICULTY_TO_INDEX, LANES_4B
from rhythm_ai.model import ChartGenerator
from rhythm_ai.postprocess import logits_to_chart_events
from scripts.evaluate_chart import evaluate_chart, find_reference, load_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sweep generation thresholds and score candidates against a reference chart."
    )
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--bpm", required=True, type=float)
    parser.add_argument("--reference-jsonl", type=Path, default=Path("data/djmax_4b_charts.jsonl"))
    parser.add_argument("--reference-title", required=True)
    parser.add_argument("--reference-difficulty", required=True)
    parser.add_argument("--output-chart", required=True, type=Path)
    parser.add_argument("--output-results", required=True, type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--tap-thresholds",
        default="0.735,0.745,0.755,0.765,0.775,0.785,0.795",
        help="comma-separated global tap threshold candidates",
    )
    parser.add_argument(
        "--hold-thresholds",
        default="0.10,0.12,0.14,0.16,0.18,0.20,0.22",
        help="comma-separated global hold threshold candidates",
    )
    parser.add_argument(
        "--lane-adjustments",
        default="0,0,0,0;-0.015,0.015,0.015,-0.015;-0.025,0.025,0.025,-0.025;-0.035,0.03,0.03,-0.035",
        help="semicolon-separated lane tap threshold offsets",
    )
    parser.add_argument(
        "--min-hold-seconds",
        default="0.10,0.14,0.18,0.22",
        help="comma-separated minimum hold duration candidates",
    )
    parser.add_argument(
        "--min-tap-gap-seconds",
        default="0.08,0.09,0.10,0.11,0.12",
        help="comma-separated minimum tap gap candidates",
    )
    parser.add_argument("--window-beats", type=float, default=4.0)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    device = resolve_device(args.device)
    checkpoint = torch.load(args.checkpoint, map_location=device)
    model = ChartGenerator(**checkpoint["model_config"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    audio_config = checkpoint["audio_config"]
    features = audio_to_features(
        args.audio,
        sample_rate=audio_config["sample_rate"],
        n_fft=audio_config["n_fft"],
        hop_length=audio_config["hop_length"],
        n_mels=audio_config["n_mels"],
    ).unsqueeze(0)

    with torch.no_grad():
        model_input = features.to(device)
        if model.difficulty_count > 0:
            difficulty_name = args.reference_difficulty
            difficulty = torch.tensor(
                [DIFFICULTY_TO_INDEX[difficulty_name]],
                device=device,
            )
            logits = model(model_input, difficulty).squeeze(0).cpu().numpy()
        else:
            logits = model(model_input).squeeze(0).cpu().numpy()

    reference = find_reference(
        load_jsonl(args.reference_jsonl),
        args.reference_title,
        args.reference_difficulty,
    )
    if reference is None:
        raise SystemExit("reference chart not found")
    reference_metrics = evaluate_chart(reference, window_beats=args.window_beats)

    tap_candidates = parse_float_list(args.tap_thresholds)
    hold_candidates = parse_float_list(args.hold_thresholds)
    lane_adjustments = parse_lane_adjustments(args.lane_adjustments)
    min_hold_candidates = parse_float_list(args.min_hold_seconds)
    min_tap_gap_candidates = parse_float_list(args.min_tap_gap_seconds)

    results: list[dict] = []
    for tap_threshold, hold_threshold, lane_delta, min_hold_seconds, min_tap_gap_seconds in product(
        tap_candidates,
        hold_candidates,
        lane_adjustments,
        min_hold_candidates,
        min_tap_gap_candidates,
    ):
        lane_taps = [round(max(0.01, tap_threshold + delta), 6) for delta in lane_delta]
        events = logits_to_chart_events(
            logits,
            bpm=args.bpm,
            frame_seconds=audio_config["frame_seconds"],
            tap_threshold=tap_threshold,
            hold_threshold=hold_threshold,
            tap_thresholds=lane_taps,
            min_tap_gap_seconds=min_tap_gap_seconds,
            min_hold_seconds=min_hold_seconds,
        )
        chart = build_chart(
            args,
            events,
            generator={
                "checkpoint": str(args.checkpoint),
                "tapThreshold": tap_threshold,
                "holdThreshold": hold_threshold,
                "tapThresholds": lane_taps,
                "laneAdjustment": lane_delta,
                "minTapGapSeconds": min_tap_gap_seconds,
                "minHoldSeconds": min_hold_seconds,
            },
        )
        metrics = evaluate_chart(chart, window_beats=args.window_beats)
        results.append(
            {
                "score": round(score_metrics(metrics, reference_metrics), 6),
                "generator": chart["generator"],
                "metrics": metrics,
            }
        )

    results.sort(key=lambda item: item["score"])
    best = results[0]
    best_events = logits_to_chart_events(
        logits,
        bpm=args.bpm,
        frame_seconds=audio_config["frame_seconds"],
        tap_threshold=best["generator"]["tapThreshold"],
        hold_threshold=best["generator"]["holdThreshold"],
        tap_thresholds=best["generator"]["tapThresholds"],
        min_tap_gap_seconds=best["generator"]["minTapGapSeconds"],
        min_hold_seconds=best["generator"]["minHoldSeconds"],
    )
    best_chart = build_chart(args, best_events, generator=best["generator"])

    args.output_chart.parent.mkdir(parents=True, exist_ok=True)
    args.output_chart.write_text(
        json.dumps(best_chart, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_results.parent.mkdir(parents=True, exist_ok=True)
    args.output_results.write_text(
        json.dumps(
            {
                "reference": reference_metrics,
                "best": best,
                "top": results[: args.top],
                "results": results,
                "candidateCount": len(results),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"candidates: {len(results)}")
    print(f"best score: {best['score']}")
    print(
        "best params: "
        f"tap={best['generator']['tapThreshold']} "
        f"hold={best['generator']['holdThreshold']} "
        f"laneTaps={best['generator']['tapThresholds']} "
        f"minHold={best['generator']['minHoldSeconds']}"
    )
    print_top(results[: args.top], reference_metrics)
    print(f"output chart: {args.output_chart}")
    print(f"output results: {args.output_results}")
    return 0


def build_chart(args: argparse.Namespace, events: list[dict], *, generator: dict) -> dict:
    return {
        "title": args.title,
        "mode": "4B",
        "difficulty": "AI",
        "bpm": {"min": args.bpm, "max": args.bpm},
        "noteCount": len(events),
        "events": events,
        "generator": generator,
    }


def score_metrics(candidate: dict, reference: dict) -> float:
    lane_error = sum(
        abs(candidate["laneRatios"][lane] - reference["laneRatios"][lane])
        for lane in LANES_4B
    )
    return (
        relative_error(candidate["noteCount"], reference["noteCount"]) * 2.2
        + relative_error(candidate["notesPerSecond"], reference["notesPerSecond"]) * 1.2
        + relative_error(candidate["holdCount"], reference["holdCount"]) * 1.8
        + relative_error(candidate["density"]["max"], reference["density"]["max"]) * 2.2
        + relative_error(candidate["density"]["p95"], reference["density"]["p95"]) * 1.2
        + lane_error * 3.5
    )


def relative_error(candidate: float, reference: float) -> float:
    if reference == 0:
        return 0.0 if candidate == 0 else 1.0
    return abs(candidate / reference - 1.0)


def parse_float_list(value: str) -> list[float]:
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def parse_lane_adjustments(value: str) -> list[list[float]]:
    adjustments = []
    for group in value.split(";"):
        if not group.strip():
            continue
        lanes = parse_float_list(group)
        if len(lanes) != len(LANES_4B):
            raise argparse.ArgumentTypeError("each lane adjustment must contain 4 values")
        adjustments.append(lanes)
    return adjustments


def print_top(results: list[dict], reference: dict) -> None:
    print("top candidates:")
    for index, item in enumerate(results, start=1):
        metrics = item["metrics"]
        generator = item["generator"]
        print(
            f"{index:02d}. score={item['score']} "
            f"notes={metrics['noteCount']}/{reference['noteCount']} "
            f"holds={metrics['holdCount']}/{reference['holdCount']} "
            f"nps={metrics['notesPerSecond']}/{reference['notesPerSecond']} "
            f"maxDensity={metrics['density']['max']}/{reference['density']['max']} "
            f"tap={generator['tapThreshold']} hold={generator['holdThreshold']} "
            f"laneTaps={generator['tapThresholds']} "
            f"minGap={generator['minTapGapSeconds']} minHold={generator['minHoldSeconds']}"
        )


def resolve_device(device: str) -> torch.device:
    if device != "auto":
        return torch.device(device)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


if __name__ == "__main__":
    raise SystemExit(main())
