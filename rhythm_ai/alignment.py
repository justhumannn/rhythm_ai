from __future__ import annotations

import re
import statistics
from pathlib import Path

import numpy as np
import torch
import torchaudio

from rhythm_ai.chart import beat_to_seconds, bpm_for_chart


GAMEPLAY_MODE_PATTERN = re.compile(r"(?<!\d)([4568])B(?!\w)", re.IGNORECASE)


def detect_gameplay_mode(path: str | Path) -> str | None:
    match = GAMEPLAY_MODE_PATTERN.search(Path(path).stem)
    return f"{match.group(1)}B" if match else None


def has_constant_bpm(chart: dict) -> bool:
    bpm = chart.get("bpm") or {}
    return float(bpm.get("min") or 0) == float(bpm.get("max") or 0)


def audio_onset_strength(
    path: str | Path,
    *,
    sample_rate: int = 22050,
    n_fft: int = 2048,
    hop_length: int = 512,
    n_mels: int = 64,
) -> tuple[np.ndarray, float]:
    waveform, original_rate = torchaudio.load(str(path))
    waveform = waveform.mean(dim=0)
    if original_rate != sample_rate:
        waveform = torchaudio.functional.resample(
            waveform,
            original_rate,
            sample_rate,
        )

    mel = torchaudio.transforms.MelSpectrogram(
        sample_rate=sample_rate,
        n_fft=n_fft,
        hop_length=hop_length,
        n_mels=n_mels,
        power=2.0,
    )(waveform)
    log_mel = torch.log1p(mel)
    flux = torch.relu(log_mel[:, 1:] - log_mel[:, :-1]).mean(dim=0)
    values = np.concatenate(([0.0], flux.cpu().numpy()))
    values = (values - np.median(values)) / (np.std(values) + 1e-6)
    return np.maximum(values, 0.0), hop_length / sample_rate


def estimate_chart_audio_offset(
    chart: dict,
    onset_strength: np.ndarray,
    *,
    frame_seconds: float,
    max_offset_seconds: float = 5.0,
) -> dict:
    chart_onsets = np.zeros(len(onset_strength), dtype=np.float32)
    bpm = bpm_for_chart(chart)
    for event in chart.get("events", []):
        frame = round(
            beat_to_seconds(float(event["beat"]), bpm) / frame_seconds
        )
        if 0 <= frame < len(chart_onsets):
            chart_onsets[frame] += 1.0

    kernel_positions = np.arange(-2, 3, dtype=np.float32)
    kernel = np.exp(-0.5 * kernel_positions**2)
    kernel /= kernel.sum()
    chart_onsets = np.convolve(chart_onsets, kernel, mode="same")
    chart_onsets = (chart_onsets - chart_onsets.mean()) / (
        chart_onsets.std() + 1e-6
    )

    max_shift = round(max_offset_seconds / frame_seconds)
    scores: list[tuple[float, int]] = []
    for shift in range(-max_shift, max_shift + 1):
        if shift >= 0:
            audio_values = onset_strength[shift:]
            chart_values = chart_onsets[: len(audio_values)]
        else:
            chart_values = chart_onsets[-shift:]
            audio_values = onset_strength[: len(chart_values)]
        score = (
            float(np.mean(audio_values * chart_values))
            if len(audio_values)
            else -float("inf")
        )
        scores.append((score, shift))

    scores.sort(reverse=True)
    best_score, best_shift = scores[0]
    separated_scores = [
        score
        for score, shift in scores[1:]
        if abs(shift - best_shift) * frame_seconds >= 0.15
    ]
    second_score = separated_scores[0] if separated_scores else scores[1][0]
    return {
        "offset_seconds": best_shift * frame_seconds,
        "score": best_score,
        "margin": best_score - second_score,
    }


def summarize_alignment(results: list[dict]) -> dict:
    offsets = [float(result["offset_seconds"]) for result in results]
    return {
        "audio_offset_seconds": statistics.median(offsets),
        "alignment_score": statistics.median(
            float(result["score"]) for result in results
        ),
        "alignment_margin": statistics.median(
            float(result["margin"]) for result in results
        ),
        "alignment_spread_seconds": max(offsets) - min(offsets),
    }
