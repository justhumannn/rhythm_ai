from __future__ import annotations

import numpy as np

from rhythm_ai.chart import LANES_4B, seconds_to_beat


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def logits_to_chart_events(
    logits: np.ndarray,
    *,
    bpm: float,
    frame_seconds: float,
    tap_threshold: float = 0.45,
    hold_threshold: float = 0.50,
    min_tap_gap_seconds: float = 0.08,
    min_hold_seconds: float = 0.20,
) -> list[dict]:
    probs = sigmoid(logits)
    tap_probs = probs[:, : len(LANES_4B)]
    hold_probs = probs[:, len(LANES_4B) :]
    min_gap = max(1, int(round(min_tap_gap_seconds / frame_seconds)))
    min_hold_frames = max(1, int(round(min_hold_seconds / frame_seconds)))

    events: list[dict] = []
    hold_starts: set[tuple[int, int]] = set()

    for lane_index, lane in enumerate(LANES_4B):
        active = hold_probs[:, lane_index] >= hold_threshold
        for start, end in active_runs(active):
            if end - start < min_hold_frames:
                continue
            start_frame = nearest_peak(
                tap_probs[:, lane_index],
                start,
                max_search=min_gap * 2,
                threshold=tap_threshold * 0.65,
            )
            end_frame = end
            hold_starts.add((lane_index, start_frame))
            start_seconds = start_frame * frame_seconds
            end_seconds = end_frame * frame_seconds
            events.append(
                {
                    "type": "hold",
                    "beat": round(seconds_to_beat(start_seconds, bpm), 6),
                    "endBeat": round(seconds_to_beat(end_seconds, bpm), 6),
                    "durationBeats": round(
                        seconds_to_beat(end_seconds - start_seconds, bpm), 6
                    ),
                    "lane": lane,
                    "timeSeconds": round(start_seconds, 6),
                    "endTimeSeconds": round(end_seconds, 6),
                }
            )

        for frame in peak_frames(tap_probs[:, lane_index], tap_threshold, min_gap):
            if (lane_index, frame) in hold_starts:
                continue
            seconds = frame * frame_seconds
            events.append(
                {
                    "type": "tap",
                    "beat": round(seconds_to_beat(seconds, bpm), 6),
                    "lane": lane,
                    "timeSeconds": round(seconds, 6),
                }
            )

    events.sort(key=lambda event: (event["beat"], event["lane"], event["type"]))
    return events


def peak_frames(values: np.ndarray, threshold: float, min_gap: int) -> list[int]:
    candidates = np.where(values >= threshold)[0]
    peaks: list[int] = []
    last = -min_gap
    for frame in candidates:
        left = max(0, frame - 1)
        right = min(len(values), frame + 2)
        if values[frame] < values[left:right].max():
            continue
        if frame - last < min_gap:
            if peaks and values[frame] > values[peaks[-1]]:
                peaks[-1] = int(frame)
                last = int(frame)
            continue
        peaks.append(int(frame))
        last = int(frame)
    return peaks


def active_runs(active: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(active):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(active)))
    return runs


def nearest_peak(
    values: np.ndarray,
    frame: int,
    *,
    max_search: int,
    threshold: float,
) -> int:
    start = max(0, frame - max_search)
    end = min(len(values), frame + max_search + 1)
    local = values[start:end]
    if len(local) == 0:
        return frame
    offset = int(local.argmax())
    peak = start + offset
    return peak if values[peak] >= threshold else frame
