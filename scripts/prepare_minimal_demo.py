#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import wave
from pathlib import Path

import numpy as np


TITLE = "Minimal Demo Pulse"
BPM = 120.0
SAMPLE_RATE = 22050
DURATION_SECONDS = 12.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a copyright-free WAV and matching chart for the minimal demo."
    )
    parser.add_argument("--output-dir", type=Path, default=Path("demo"))
    args = parser.parse_args()

    audio_dir = args.output_dir / "audio"
    data_dir = args.output_dir / "data"
    audio_path = audio_dir / f"{TITLE}.wav"
    charts_path = data_dir / "minimal_charts.jsonl"

    events = demo_events()
    audio_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    write_demo_audio(audio_path, events)
    write_demo_chart(charts_path, events)

    print(f"audio: {audio_path}")
    print(f"charts: {charts_path}")
    print(f"title: {TITLE}")
    print(f"bpm: {BPM}")
    return 0


def demo_events() -> list[dict]:
    events: list[dict] = []
    lane_sequence = ("1", "2", "3", "4", "2", "3", "1", "4")
    for index, beat in enumerate(np.arange(2.0, 22.0, 0.5)):
        lane = lane_sequence[index % len(lane_sequence)]
        if index in {8, 20, 32}:
            end_beat = float(beat + 1.5)
            events.append(
                {
                    "type": "hold",
                    "beat": float(beat),
                    "endBeat": end_beat,
                    "durationBeats": 1.5,
                    "lane": lane,
                }
            )
        else:
            events.append({"type": "tap", "beat": float(beat), "lane": lane})
    return events


def write_demo_audio(path: Path, events: list[dict]) -> None:
    sample_count = int(DURATION_SECONDS * SAMPLE_RATE)
    audio = np.zeros(sample_count, dtype=np.float64)

    for beat in np.arange(0.0, 24.0, 1.0):
        add_click(audio, beat_to_seconds(float(beat)), frequency=900.0, amplitude=0.12)

    lane_frequencies = {"1": 330.0, "2": 440.0, "3": 550.0, "4": 660.0}
    for event in events:
        start = beat_to_seconds(float(event["beat"]))
        frequency = lane_frequencies[str(event["lane"])]
        if event["type"] == "hold":
            duration = beat_to_seconds(float(event["durationBeats"]))
            add_tone(audio, start, duration, frequency, amplitude=0.20)
            add_click(audio, start, frequency=frequency * 1.5, amplitude=0.35)
        else:
            add_click(audio, start, frequency=frequency, amplitude=0.32)

    peak = float(np.max(np.abs(audio)))
    if peak > 0:
        audio = audio / peak * 0.85
    pcm = np.asarray(audio * 32767.0, dtype="<i2")
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())


def add_click(
    audio: np.ndarray,
    start_seconds: float,
    *,
    frequency: float,
    amplitude: float,
) -> None:
    add_tone(audio, start_seconds, 0.08, frequency, amplitude=amplitude)


def add_tone(
    audio: np.ndarray,
    start_seconds: float,
    duration_seconds: float,
    frequency: float,
    *,
    amplitude: float,
) -> None:
    start = max(0, int(round(start_seconds * SAMPLE_RATE)))
    end = min(len(audio), start + int(round(duration_seconds * SAMPLE_RATE)))
    if end <= start:
        return
    time = np.arange(end - start, dtype=np.float64) / SAMPLE_RATE
    envelope = np.sin(np.linspace(0.0, math.pi, end - start)) ** 2
    audio[start:end] += amplitude * np.sin(2.0 * math.pi * frequency * time) * envelope


def write_demo_chart(path: Path, events: list[dict]) -> None:
    chart = {
        "title": TITLE,
        "mode": "4B",
        "difficulty": "NM",
        "level": 1,
        "bpm": {"min": BPM, "max": BPM},
        "playtimeSeconds": DURATION_SECONDS,
        "noteCount": len(events),
        "events": events,
        "source": "generated minimal demo",
    }
    path.write_text(
        json.dumps(chart, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def beat_to_seconds(beat: float) -> float:
    return beat * 60.0 / BPM


if __name__ == "__main__":
    raise SystemExit(main())
