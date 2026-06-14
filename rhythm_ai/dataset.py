from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

import torch
from torch.utils.data import Dataset

from rhythm_ai.audio import audio_to_features
from rhythm_ai.chart import (
    DIFFICULTY_TO_INDEX,
    chart_to_frame_labels,
    load_jsonl,
    normalize_title,
)


@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int = 22050
    n_fft: int = 2048
    hop_length: int = 512
    n_mels: int = 96

    @property
    def frame_seconds(self) -> float:
        return self.hop_length / self.sample_rate


def load_audio_manifest(path: str | Path) -> dict[str, dict]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    manifest: dict[str, dict] = {}
    for row in rows:
        manifest[normalize_title(row["title"])] = row
    return manifest


class ChartAudioDataset(Dataset):
    def __init__(
        self,
        *,
        charts_path: str | Path,
        audio_manifest_path: str | Path,
        audio_config: AudioConfig,
        segment_frames: int = 512,
        samples_per_epoch: int = 4096,
        balanced_difficulty: bool = True,
        tap_radius_frames: int = 1,
        require_training_eligible: bool = False,
        exclude_gameplay_audio: bool = False,
    ) -> None:
        self.audio_config = audio_config
        self.segment_frames = segment_frames
        self.samples_per_epoch = samples_per_epoch
        self.balanced_difficulty = balanced_difficulty
        self.tap_radius_frames = tap_radius_frames
        manifest = load_audio_manifest(audio_manifest_path)

        charts = load_jsonl(charts_path)
        self.items: list[tuple[dict, str, float]] = []
        for chart in charts:
            audio_row = manifest.get(normalize_title(chart["title"]))
            if not audio_row:
                continue
            if require_training_eligible and not audio_row.get(
                "training_eligible",
                False,
            ):
                continue
            if exclude_gameplay_audio and audio_row.get("source_gameplay_mode"):
                continue
            self.items.append(
                (
                    chart,
                    audio_row["audio_path"],
                    float(audio_row.get("audio_offset_seconds", 0.0)),
                )
            )

        if not self.items:
            raise ValueError("no chart/audio pairs matched; check audio_manifest.json")

        self.items_by_difficulty: dict[
            int,
            list[tuple[dict, str, float]],
        ] = {}
        for item in self.items:
            difficulty_index = DIFFICULTY_TO_INDEX.get(item[0].get("difficulty"))
            if difficulty_index is not None:
                self.items_by_difficulty.setdefault(difficulty_index, []).append(item)
        self._feature_cache: dict[str, torch.Tensor] = {}

    def __len__(self) -> int:
        return self.samples_per_epoch

    def __getitem__(
        self,
        index: int,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        chart, audio_path, audio_offset_seconds = self._sample_item()
        difficulty_index = DIFFICULTY_TO_INDEX.get(chart.get("difficulty"), 0)
        features = self._features(audio_path)
        labels = torch.from_numpy(
            chart_to_frame_labels(
                chart,
                frame_seconds=self.audio_config.frame_seconds,
                duration_seconds=features.shape[1] * self.audio_config.frame_seconds,
                tap_radius_frames=self.tap_radius_frames,
                audio_offset_seconds=audio_offset_seconds,
            )
        )

        frames = min(features.shape[1], labels.shape[0])
        features = features[:, :frames]
        labels = labels[:frames]

        if frames >= self.segment_frames:
            start = random.randint(0, frames - self.segment_frames)
            end = start + self.segment_frames
            return (
                features[:, start:end],
                labels[start:end],
                torch.tensor(difficulty_index, dtype=torch.long),
            )

        pad = self.segment_frames - frames
        features = torch.nn.functional.pad(features, (0, pad))
        labels = torch.nn.functional.pad(labels, (0, 0, 0, pad))
        return features, labels, torch.tensor(difficulty_index, dtype=torch.long)

    def _sample_item(self) -> tuple[dict, str, float]:
        if self.balanced_difficulty and self.items_by_difficulty:
            difficulty = random.choice(tuple(self.items_by_difficulty))
            return random.choice(self.items_by_difficulty[difficulty])
        return random.choice(self.items)

    def _features(self, audio_path: str) -> torch.Tensor:
        cached = self._feature_cache.get(audio_path)
        if cached is not None:
            return cached

        features = audio_to_features(
            audio_path,
            sample_rate=self.audio_config.sample_rate,
            n_fft=self.audio_config.n_fft,
            hop_length=self.audio_config.hop_length,
            n_mels=self.audio_config.n_mels,
        )
        self._feature_cache[audio_path] = features
        return features
