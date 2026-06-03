from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable


LANES_4B = ("1", "2", "3", "4")
DIFFICULTY_TO_INDEX = {"NM": 0, "HD": 1, "MX": 2, "SC": 3}


def load_jsonl(path: str | Path) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).casefold()
    text = re.sub(r"[^0-9a-z가-힣ぁ-ゟ゠-ヿ一-龯]+", "", text)
    return text


def bpm_for_chart(chart: dict) -> float:
    bpm = chart.get("bpm") or {}
    for key in ("max", "min"):
        value = bpm.get(key)
        if value:
            return float(value)
    raise ValueError(f"chart has no usable BPM: {chart.get('title')}")


def beat_to_seconds(beat: float, bpm: float) -> float:
    return beat * 60.0 / bpm


def seconds_to_beat(seconds: float, bpm: float) -> float:
    return seconds * bpm / 60.0


def chart_duration_seconds(chart: dict) -> float:
    if chart.get("playtimeSeconds"):
        return float(chart["playtimeSeconds"])
    bpm = bpm_for_chart(chart)
    max_beat = 0.0
    for event in chart.get("events", []):
        max_beat = max(max_beat, float(event.get("endBeat", event["beat"])))
    return beat_to_seconds(max_beat + 4.0, bpm)


def chart_to_frame_labels(
    chart: dict,
    *,
    frame_seconds: float,
    lanes: Iterable[str] = LANES_4B,
    duration_seconds: float | None = None,
) -> np.ndarray:
    import numpy as np

    lanes = tuple(lanes)
    lane_to_index = {lane: index for index, lane in enumerate(lanes)}
    bpm = bpm_for_chart(chart)
    duration = duration_seconds or chart_duration_seconds(chart)
    frame_count = max(1, int(np.ceil(duration / frame_seconds)))
    labels = np.zeros((frame_count, len(lanes) * 2), dtype=np.float32)

    for event in chart.get("events", []):
        lane = str(event["lane"])
        if lane not in lane_to_index:
            continue
        lane_index = lane_to_index[lane]
        start_seconds = beat_to_seconds(float(event["beat"]), bpm)
        start_frame = int(round(start_seconds / frame_seconds))
        if not 0 <= start_frame < frame_count:
            continue

        labels[start_frame, lane_index] = 1.0
        if event["type"] == "hold":
            end_seconds = beat_to_seconds(float(event["endBeat"]), bpm)
            end_frame = int(round(end_seconds / frame_seconds))
            end_frame = min(max(end_frame, start_frame + 1), frame_count)
            labels[start_frame:end_frame, len(lanes) + lane_index] = 1.0

    return labels


def title_to_charts(charts: Iterable[dict]) -> dict[str, list[dict]]:
    mapping: dict[str, list[dict]] = {}
    for chart in charts:
        mapping.setdefault(normalize_title(chart["title"]), []).append(chart)
    return mapping
