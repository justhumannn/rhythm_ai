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
    tap_thresholds: list[float] | tuple[float, ...] | None = None,
    hold_thresholds: list[float] | tuple[float, ...] | None = None,
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
    hold_blocks: dict[int, list[tuple[int, int]]] = {}
    lane_tap_thresholds = per_lane_thresholds(tap_threshold, tap_thresholds)
    lane_hold_thresholds = per_lane_thresholds(hold_threshold, hold_thresholds)

    for lane_index, lane in enumerate(LANES_4B):
        lane_tap_threshold = lane_tap_thresholds[lane_index]
        lane_hold_threshold = lane_hold_thresholds[lane_index]
        active = hold_probs[:, lane_index] >= lane_hold_threshold
        for start, end in active_runs(active):
            if end - start < min_hold_frames:
                continue
            start_frame = nearest_peak(
                tap_probs[:, lane_index],
                start,
                max_search=min_gap * 2,
                threshold=lane_tap_threshold * 0.65,
            )
            end_frame = end
            hold_starts.add((lane_index, start_frame))
            hold_blocks.setdefault(lane_index, []).append(
                (max(0, start_frame - min_gap), min(len(active), end_frame + min_gap))
            )
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

        for frame in peak_frames(tap_probs[:, lane_index], lane_tap_threshold, min_gap):
            if (lane_index, frame) in hold_starts:
                continue
            if is_blocked_by_hold(frame, hold_blocks.get(lane_index, [])):
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

    events = dedupe_same_lane_events(events)
    events = remove_same_lane_hold_overlaps(events)
    events = remove_taps_inside_holds(events)
    events.sort(key=lambda event: (event["beat"], event["lane"], event["type"]))
    return events


def per_lane_thresholds(
    default: float,
    values: list[float] | tuple[float, ...] | None,
) -> tuple[float, float, float, float]:
    if values is None:
        return (default, default, default, default)
    if len(values) != len(LANES_4B):
        raise ValueError(f"expected {len(LANES_4B)} lane thresholds, got {len(values)}")
    return tuple(float(value) for value in values)  # type: ignore[return-value]


def is_blocked_by_hold(frame: int, blocks: list[tuple[int, int]]) -> bool:
    return any(start <= frame <= end for start, end in blocks)


def dedupe_same_lane_events(events: list[dict]) -> list[dict]:
    best_by_lane_beat: dict[tuple[str, float], dict] = {}
    for event in events:
        key = (str(event["lane"]), round(float(event["beat"]), 6))
        current = best_by_lane_beat.get(key)
        if current is None or event_priority(event) > event_priority(current):
            best_by_lane_beat[key] = event
    return list(best_by_lane_beat.values())


def event_priority(event: dict) -> tuple[int, float]:
    if event["type"] == "hold":
        return (1, float(event.get("durationBeats", 0.0)))
    return (0, 0.0)


def remove_same_lane_hold_overlaps(events: list[dict]) -> list[dict]:
    holds_by_lane: dict[str, list[dict]] = {}
    others: list[dict] = []
    for event in events:
        if event["type"] == "hold":
            holds_by_lane.setdefault(str(event["lane"]), []).append(event)
        else:
            others.append(event)

    kept_holds: list[dict] = []
    for lane_holds in holds_by_lane.values():
        occupied_until = -float("inf")
        for hold in sorted(
            lane_holds,
            key=lambda event: (
                float(event["beat"]),
                -float(event.get("durationBeats", 0.0)),
                -float(event.get("endBeat", event["beat"])),
            ),
        ):
            start = float(hold["beat"])
            end = float(hold.get("endBeat", hold["beat"]))
            if start < occupied_until - 1e-6:
                continue
            kept_holds.append(hold)
            occupied_until = max(occupied_until, end)
    return others + kept_holds


def remove_taps_inside_holds(events: list[dict]) -> list[dict]:
    holds_by_lane: dict[str, list[tuple[float, float]]] = {}
    for event in events:
        if event["type"] != "hold":
            continue
        holds_by_lane.setdefault(str(event["lane"]), []).append(
            (float(event["beat"]), float(event.get("endBeat", event["beat"])))
        )

    cleaned: list[dict] = []
    for event in events:
        if event["type"] != "tap":
            cleaned.append(event)
            continue
        lane_holds = holds_by_lane.get(str(event["lane"]), [])
        beat = float(event["beat"])
        if any(start - 1e-6 <= beat <= end + 1e-6 for start, end in lane_holds):
            continue
        cleaned.append(event)
    return cleaned


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
