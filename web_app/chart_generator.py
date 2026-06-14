from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import torch

from rhythm_ai.audio import audio_to_features
from rhythm_ai.model import ChartGenerator
from rhythm_ai.postprocess import (
    dedupe_same_lane_events,
    logits_to_chart_events,
    remove_same_lane_hold_overlaps,
    remove_taps_inside_holds,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALIGNED_CHECKPOINT = ROOT / "checkpoints" / "djmax_4b_aligned.pt"
DEFAULT_CONDITIONAL_CHECKPOINT = ROOT / "checkpoints" / "djmax_4b_conditional.pt"
DEFAULT_BASELINE_CHECKPOINT = ROOT / "checkpoints" / "djmax_4b_baseline.pt"


DIFFICULTY_TAP_BASE = {
    "easy": 0.84,
    "normal": 0.78,
    "hard": 0.725,
    "expert": 0.68,
}
WEB_DIFFICULTY_TO_INDEX = {
    "easy": 0,
    "normal": 1,
    "hard": 2,
    "expert": 3,
}


def generate_chart(
    *,
    audio_path: str | Path,
    title: str,
    bpm: float,
    difficulty: str,
    tap_ratio: float,
    hold_ratio: float,
    key_count: int,
) -> tuple[dict, dict]:
    if key_count != 4:
        raise ValueError("현재 학습된 모델은 4B만 지원합니다.")

    model, checkpoint, device, checkpoint_path = load_model()
    audio_config = checkpoint["audio_config"]
    features = audio_to_features(
        Path(audio_path),
        sample_rate=audio_config["sample_rate"],
        n_fft=audio_config["n_fft"],
        hop_length=audio_config["hop_length"],
        n_mels=audio_config["n_mels"],
    ).unsqueeze(0)

    with torch.no_grad():
        model_input = features.to(device)
        if model.difficulty_count > 0:
            difficulty_index = WEB_DIFFICULTY_TO_INDEX.get(difficulty.lower(), 2)
            condition = torch.tensor([difficulty_index], device=device)
            logits = model(model_input, condition).squeeze(0).cpu().numpy()
        else:
            logits = model(model_input).squeeze(0).cpu().numpy()

    thresholds = thresholds_for_settings(difficulty, tap_ratio, hold_ratio)
    events = logits_to_chart_events(
        logits,
        bpm=bpm,
        frame_seconds=audio_config["frame_seconds"],
        tap_threshold=thresholds["tap_threshold"],
        hold_threshold=thresholds["hold_threshold"],
        tap_thresholds=thresholds["tap_thresholds"],
        min_tap_gap_seconds=thresholds["min_tap_gap_seconds"],
        min_hold_seconds=thresholds["min_hold_seconds"],
        beat_snap=thresholds["beat_snap"],
    )
    events = limit_hold_ratio(events, hold_ratio)
    chart = {
        "title": title,
        "mode": f"{key_count}B",
        "difficulty": difficulty,
        "bpm": {"min": bpm, "max": bpm},
        "noteCount": len(events),
        "events": events,
        "generator": {
            "checkpoint": str(checkpoint_path),
            **thresholds,
            "tapRatio": tap_ratio,
            "holdRatio": hold_ratio,
            "keyCount": key_count,
        },
    }
    return chart, thresholds


def thresholds_for_settings(difficulty: str, tap_ratio: float, hold_ratio: float) -> dict:
    difficulty_key = difficulty.lower()
    base_tap = DIFFICULTY_TAP_BASE.get(difficulty_key, DIFFICULTY_TAP_BASE["hard"])
    tap_pressure = clamp((tap_ratio - 50.0) / 50.0, -1.0, 1.0)
    hold_pressure = clamp((hold_ratio - 50.0) / 50.0, -1.0, 1.0)

    tap_threshold = clamp(base_tap - tap_pressure * 0.07, 0.55, 0.92)
    hold_threshold = 1.1 if hold_ratio <= 0 else clamp(0.26 - hold_pressure * 0.10, 0.12, 0.46)

    # The baseline model tends to overuse center lanes, so outer lanes use a lower threshold.
    lane_adjust = (-0.04, 0.03, 0.03, -0.04)
    tap_thresholds = [round(clamp(tap_threshold + delta, 0.50, 0.95), 6) for delta in lane_adjust]
    min_tap_gap_seconds = clamp(0.11 - tap_pressure * 0.03, 0.07, 0.14)

    return {
        "tap_threshold": round(tap_threshold, 6),
        "hold_threshold": round(hold_threshold, 6),
        "tap_thresholds": tap_thresholds,
        "min_tap_gap_seconds": round(min_tap_gap_seconds, 6),
        "min_hold_seconds": 0.10,
        "beat_snap": 0.125,
    }


def limit_hold_ratio(events: list[dict], hold_ratio: float) -> list[dict]:
    if hold_ratio <= 0:
        return sorted(
            [event for event in events if event["type"] != "hold"],
            key=lambda event: (event["beat"], event["lane"], event["type"]),
        )

    target_fraction = clamp(hold_ratio / 100.0 * 0.16, 0.0, 0.16)
    total = len(events)
    if total == 0:
        return events

    holds = [event for event in events if event["type"] == "hold"]
    max_holds = int(round(total * target_fraction))
    if len(holds) <= max_holds:
        return events

    keep_ids = {
        id(event)
        for event in sorted(
            holds,
            key=lambda event: (
                -float(event.get("durationBeats", 0.0)),
                float(event["beat"]),
                str(event["lane"]),
            ),
        )[:max_holds]
    }
    limited = [
        event
        for event in events
        if event["type"] != "hold" or id(event) in keep_ids
    ]
    limited.sort(key=lambda event: (event["beat"], event["lane"], event["type"]))
    return limited


def chart_to_json(chart: dict) -> str:
    return json.dumps(chart, ensure_ascii=False)


def chart_from_json(chart_json: str, hold_ratio: float | None = None) -> dict:
    chart = json.loads(chart_json)
    if chart.get("events"):
        events = dedupe_same_lane_events(chart["events"])
        events = remove_same_lane_hold_overlaps(events)
        events = remove_taps_inside_holds(events)
        if hold_ratio is not None:
            events = limit_hold_ratio(events, hold_ratio)
        events.sort(key=lambda event: (event["beat"], event["lane"], event["type"]))
        chart["events"] = events
        chart["noteCount"] = len(events)
    return chart


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def load_model():
    checkpoint_path = resolve_checkpoint_path()
    modified_ns = checkpoint_path.stat().st_mtime_ns
    model, checkpoint, device = load_model_cached(str(checkpoint_path), modified_ns)
    return model, checkpoint, device, checkpoint_path


@lru_cache(maxsize=2)
def load_model_cached(checkpoint_path: str, modified_ns: int):
    if torch.cuda.is_available():
        device = torch.device("cuda")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")

    checkpoint = torch.load(checkpoint_path, map_location=device)
    model = ChartGenerator(**checkpoint["model_config"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    return model, checkpoint, device


def resolve_checkpoint_path() -> Path:
    configured = os.environ.get("RHYTHM_CHECKPOINT")
    if configured:
        return Path(configured).expanduser().resolve()
    if DEFAULT_ALIGNED_CHECKPOINT.exists():
        return DEFAULT_ALIGNED_CHECKPOINT
    if DEFAULT_CONDITIONAL_CHECKPOINT.exists():
        return DEFAULT_CONDITIONAL_CHECKPOINT
    return DEFAULT_BASELINE_CHECKPOINT
