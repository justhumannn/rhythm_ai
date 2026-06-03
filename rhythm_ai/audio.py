from __future__ import annotations

from pathlib import Path

import torch
import torchaudio


def load_audio(path: str | Path, sample_rate: int) -> torch.Tensor:
    waveform, original_rate = torchaudio.load(str(path))
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if original_rate != sample_rate:
        waveform = torchaudio.functional.resample(waveform, original_rate, sample_rate)
    return waveform.squeeze(0)


def log_mel_spectrogram(
    waveform: torch.Tensor,
    *,
    sample_rate: int,
    n_fft: int,
    hop_length: int,
    n_mels: int,
) -> torch.Tensor:
    transform = torchaudio.transforms.MelSpectrogram(
        sample_rate=sample_rate,
        n_fft=n_fft,
        hop_length=hop_length,
        n_mels=n_mels,
        power=2.0,
    )
    mel = transform(waveform)
    return torch.log1p(mel)


def audio_to_features(
    path: str | Path,
    *,
    sample_rate: int,
    n_fft: int,
    hop_length: int,
    n_mels: int,
) -> torch.Tensor:
    waveform = load_audio(path, sample_rate)
    features = log_mel_spectrogram(
        waveform,
        sample_rate=sample_rate,
        n_fft=n_fft,
        hop_length=hop_length,
        n_mels=n_mels,
    )
    mean = features.mean(dim=1, keepdim=True)
    std = features.std(dim=1, keepdim=True).clamp_min(1e-5)
    return (features - mean) / std
