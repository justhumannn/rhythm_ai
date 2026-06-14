from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
import torchaudio

from rhythm_ai.chart import load_jsonl, normalize_title
from rhythm_ai.matching import best_chart_match


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHARTS_PATH = ROOT / "data" / "djmax_4b_charts.jsonl"
HOP_LENGTH = 512
TARGET_SAMPLE_RATE = 22050


@dataclass(frozen=True)
class BpmCandidate:
    bpm: float
    relative_score: float


@dataclass(frozen=True)
class BpmAnalysis:
    bpm: float
    confidence: float
    source: str
    stable: bool
    ambiguous: bool
    local_bpm_median: float | None
    local_bpm_spread: float | None
    candidates: tuple[BpmCandidate, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_bpm(
    audio_path: str | Path,
    *,
    title: str | None = None,
    min_bpm: float = 60.0,
    max_bpm: float = 360.0,
) -> float:
    return analyze_bpm(
        audio_path,
        title=title,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
    ).bpm


def analyze_bpm(
    audio_path: str | Path,
    *,
    title: str | None = None,
    min_bpm: float = 60.0,
    max_bpm: float = 360.0,
) -> BpmAnalysis:
    waveform, sample_rate = load_mono_audio(audio_path)
    onset = onset_envelope(waveform, sample_rate)
    if len(onset) < 8 or float(onset.max()) <= 0:
        return fallback_analysis()

    frame_rate = sample_rate / HOP_LENGTH
    raw_candidates = interval_tempo_scores(onset, frame_rate, min_bpm, max_bpm)
    if not raw_candidates:
        return fallback_analysis()

    candidates = distinct_candidates(raw_candidates)
    local_bpms = local_tempo_estimates(
        onset,
        frame_rate,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
    )
    local_median, local_spread, stable = summarize_local_tempos(local_bpms)

    catalog_bpm = catalog_bpm_for_title(title) if title else None
    if catalog_bpm is not None and candidate_support(raw_candidates, catalog_bpm) >= 0.35:
        support = candidate_support(raw_candidates, catalog_bpm)
        confidence = min(0.99, 0.82 + support * 0.17)
        return BpmAnalysis(
            bpm=round(catalog_bpm, 3),
            confidence=round(confidence, 3),
            source="djmax_catalog",
            stable=stable,
            ambiguous=False,
            local_bpm_median=local_median,
            local_bpm_spread=local_spread,
            candidates=include_candidate(
                candidates,
                catalog_bpm,
                support,
            ),
        )

    selected = select_canonical_tempo(
        raw_candidates,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
    )
    selected = refine_with_local_tempos(selected, local_bpms)
    ambiguous = has_harmonic_ambiguity(selected, raw_candidates)
    confidence = tempo_confidence(
        selected,
        raw_candidates,
        local_bpms,
        stable=stable,
        ambiguous=ambiguous,
    )
    return BpmAnalysis(
        bpm=round(selected, 3),
        confidence=round(confidence, 3),
        source="audio_analysis",
        stable=stable,
        ambiguous=ambiguous,
        local_bpm_median=local_median,
        local_bpm_spread=local_spread,
        candidates=candidates,
    )


def load_mono_audio(path: str | Path) -> tuple[torch.Tensor, int]:
    waveform, sample_rate = torchaudio.load(str(path))
    waveform = waveform.mean(dim=0)
    if sample_rate != TARGET_SAMPLE_RATE:
        waveform = torchaudio.functional.resample(
            waveform,
            sample_rate,
            TARGET_SAMPLE_RATE,
        )
        sample_rate = TARGET_SAMPLE_RATE
    return waveform, sample_rate


def fallback_analysis() -> BpmAnalysis:
    return BpmAnalysis(
        bpm=120.0,
        confidence=0.0,
        source="fallback",
        stable=False,
        ambiguous=True,
        local_bpm_median=None,
        local_bpm_spread=None,
        candidates=(),
    )


def onset_envelope(waveform: torch.Tensor, sample_rate: int) -> np.ndarray:
    n_fft = 2048
    window = torch.hann_window(n_fft, device=waveform.device)
    spectrogram = torch.stft(
        waveform,
        n_fft=n_fft,
        hop_length=HOP_LENGTH,
        window=window,
        return_complex=True,
    ).abs()
    log_spectrogram = torch.log1p(spectrogram)
    flux = torch.relu(log_spectrogram[:, 1:] - log_spectrogram[:, :-1]).sum(dim=0)
    envelope = flux.cpu().numpy()
    if len(envelope) >= 3:
        envelope = np.convolve(envelope, np.ones(3) / 3.0, mode="same")
    envelope = envelope - np.percentile(envelope, 20)
    return np.maximum(envelope, 0)


def interval_tempo_scores(
    onset: np.ndarray,
    frame_rate: float,
    min_bpm: float,
    max_bpm: float,
) -> list[tuple[float, float]]:
    peaks = pick_peaks(onset, frame_rate)
    if len(peaks) < 4:
        return []

    diffs = peak_differences(peaks, frame_rate, min_bpm)
    if len(diffs) == 0:
        return []

    scores: list[tuple[float, float]] = []
    for bpm in np.arange(min_bpm, max_bpm + 0.001, 0.1):
        period = frame_rate * 60.0 / bpm
        score = 0.0
        for multiple, weight in (
            (1.0, 1.0),
            (2.0, 0.7),
            (3.0, 0.35),
            (4.0, 0.2),
            (0.5, 0.4),
        ):
            target = period * multiple
            tolerance = max(1.0, target * 0.04)
            distance = np.abs(diffs - target)
            score += weight * float(np.exp(-((distance / tolerance) ** 2)).sum())
        scores.append((score, round(float(bpm), 3)))
    return sorted(scores, reverse=True)


def distinct_candidates(
    scores: list[tuple[float, float]],
    *,
    limit: int = 5,
    separation_bpm: float = 2.0,
) -> tuple[BpmCandidate, ...]:
    if not scores:
        return ()
    top_score = max(scores[0][0], 1e-9)
    selected: list[BpmCandidate] = []
    for score, bpm in scores:
        if any(abs(bpm - item.bpm) < separation_bpm for item in selected):
            continue
        selected.append(
            BpmCandidate(
                bpm=round(float(bpm), 3),
                relative_score=round(float(score / top_score), 3),
            )
        )
        if len(selected) >= limit:
            break
    return tuple(selected)


def include_candidate(
    candidates: tuple[BpmCandidate, ...],
    bpm: float,
    support: float,
) -> tuple[BpmCandidate, ...]:
    if any(abs(candidate.bpm - bpm) < 0.2 for candidate in candidates):
        return candidates
    return (
        BpmCandidate(
            bpm=round(bpm, 3),
            relative_score=round(support, 3),
        ),
        *candidates[:4],
    )


def select_canonical_tempo(
    scores: list[tuple[float, float]],
    *,
    min_bpm: float,
    max_bpm: float,
) -> float:
    preferred = [
        (score, bpm)
        for score, bpm in scores
        if max(min_bpm, 70.0) <= bpm <= min(max_bpm, 220.0)
    ]
    score, bpm = preferred[0] if preferred else scores[0]
    if bpm < 110.0 and bpm * 2.0 <= max_bpm:
        doubled_score = score_near(scores, bpm * 2.0)
        if doubled_score >= score * 0.68:
            bpm *= 2.0
    return float(bpm)


def local_tempo_estimates(
    onset: np.ndarray,
    frame_rate: float,
    *,
    min_bpm: float,
    max_bpm: float,
    window_seconds: float = 20.0,
    hop_seconds: float = 10.0,
) -> list[float]:
    window_frames = max(8, round(window_seconds * frame_rate))
    hop_frames = max(1, round(hop_seconds * frame_rate))
    if len(onset) <= window_frames:
        windows = [onset]
    else:
        windows = [
            onset[start : start + window_frames]
            for start in range(0, len(onset) - window_frames + 1, hop_frames)
        ]

    estimates: list[float] = []
    for window in windows:
        if float(window.max()) <= 0:
            continue
        scores = interval_tempo_scores(window, frame_rate, min_bpm, max_bpm)
        if scores:
            estimates.append(
                select_canonical_tempo(
                    scores,
                    min_bpm=min_bpm,
                    max_bpm=max_bpm,
                )
            )
    return estimates


def summarize_local_tempos(
    bpms: list[float],
) -> tuple[float | None, float | None, bool]:
    if not bpms:
        return None, None, False
    normalized = normalize_tempo_family(bpms)
    median = statistics.median(normalized)
    deviations = [abs(value - median) for value in normalized]
    spread = statistics.median(deviations)
    stable = spread <= 2.0 and (
        sum(abs(value - median) <= 3.0 for value in normalized) / len(normalized)
        >= 0.7
    )
    return round(median, 3), round(spread, 3), stable


def normalize_tempo_family(bpms: list[float]) -> list[float]:
    if not bpms:
        return []
    center = statistics.median(bpms)
    normalized: list[float] = []
    for bpm in bpms:
        options = (bpm / 2.0, bpm, bpm * 2.0)
        normalized.append(min(options, key=lambda value: abs(value - center)))
    return normalized


def refine_with_local_tempos(global_bpm: float, local_bpms: list[float]) -> float:
    compatible: list[float] = []
    for bpm in local_bpms:
        options = (bpm / 2.0, bpm, bpm * 2.0)
        nearest = min(options, key=lambda value: abs(value - global_bpm))
        if abs(nearest - global_bpm) <= max(3.0, global_bpm * 0.025):
            compatible.append(nearest)
    if len(compatible) < 2:
        return global_bpm
    return float(statistics.median([global_bpm, *compatible]))


def tempo_confidence(
    bpm: float,
    scores: list[tuple[float, float]],
    local_bpms: list[float],
    *,
    stable: bool,
    ambiguous: bool,
) -> float:
    support = candidate_support(scores, bpm)
    local_support = 0.0
    if local_bpms:
        matched = 0
        for local_bpm in local_bpms:
            options = (local_bpm / 2.0, local_bpm, local_bpm * 2.0)
            if min(abs(value - bpm) for value in options) <= max(3.0, bpm * 0.025):
                matched += 1
        local_support = matched / len(local_bpms)
    confidence = support * 0.55 + local_support * 0.35 + (0.1 if stable else 0.0)
    if ambiguous:
        confidence *= 0.75
    return max(0.0, min(0.9, confidence))


def has_harmonic_ambiguity(
    bpm: float,
    scores: list[tuple[float, float]],
) -> bool:
    if not scores:
        return True
    selected_score = score_near(scores, bpm)
    harmonic_score = max(
        score_near(scores, bpm / 2.0),
        score_near(scores, bpm * 2.0),
    )
    return harmonic_score >= selected_score * 0.9


def candidate_support(
    scores: list[tuple[float, float]],
    bpm: float,
) -> float:
    if not scores:
        return 0.0
    top_score = max(scores[0][0], 1e-9)
    direct = score_near(scores, bpm)
    harmonic = max(
        score_near(scores, bpm / 2.0),
        score_near(scores, bpm * 2.0),
    )
    return min(1.0, (direct + harmonic * 0.25) / top_score)


def score_near(
    scores: list[tuple[float, float]],
    bpm: float,
    tolerance: float = 0.11,
) -> float:
    nearest = min(scores, key=lambda item: abs(item[1] - bpm))
    return nearest[0] if abs(nearest[1] - bpm) <= tolerance else 0.0


@lru_cache(maxsize=1)
def catalog_charts() -> list[dict]:
    if not DEFAULT_CHARTS_PATH.exists():
        return []
    return load_jsonl(DEFAULT_CHARTS_PATH)


def catalog_bpm_for_title(title: str) -> float | None:
    charts = catalog_charts()
    safe_title = title.replace("/", " ").replace("\\", " ")
    match = best_chart_match(Path(f"{safe_title}.wav"), charts)
    if match is None or match.score < 16:
        return None

    matched_title = normalize_title(match.chart["title"])
    bpms = {
        float(chart["bpm"]["max"])
        for chart in charts
        if normalize_title(chart["title"]) == matched_title
        and chart.get("bpm", {}).get("min")
        and float(chart["bpm"]["min"]) == float(chart["bpm"]["max"])
    }
    return next(iter(bpms)) if len(bpms) == 1 else None


def pick_peaks(onset: np.ndarray, frame_rate: float) -> np.ndarray:
    threshold = float(np.percentile(onset, 85))
    min_gap = max(1, int(round(frame_rate * 0.08)))
    peaks: list[int] = []
    last = -min_gap
    for index in range(1, len(onset) - 1):
        if index - last < min_gap:
            continue
        if onset[index] < threshold:
            continue
        if onset[index] < onset[index - 1] or onset[index] < onset[index + 1]:
            continue
        peaks.append(index)
        last = index
    return np.array(peaks, dtype=np.int32)


def peak_differences(
    peaks: np.ndarray,
    frame_rate: float,
    min_bpm: float,
) -> np.ndarray:
    max_interval = frame_rate * 60.0 / min_bpm * 4.0
    diffs: list[int] = []
    for start_index, peak in enumerate(peaks):
        end_index = start_index + 1
        while end_index < len(peaks) and peaks[end_index] - peak <= max_interval:
            diffs.append(int(peaks[end_index] - peak))
            end_index += 1
    return np.array(diffs, dtype=np.float32)
