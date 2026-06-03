#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rhythm_ai.dataset import AudioConfig, ChartAudioDataset
from rhythm_ai.model import ChartGenerator


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a DJMAX 4B chart model.")
    parser.add_argument("--charts", default="data/djmax_4b_charts.jsonl")
    parser.add_argument("--audio-manifest", required=True)
    parser.add_argument("--output", default="checkpoints/djmax_4b_baseline.pt", type=Path)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--samples-per-epoch", type=int, default=4096)
    parser.add_argument("--segment-frames", type=int, default=512)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--sample-rate", type=int, default=22050)
    parser.add_argument("--n-fft", type=int, default=2048)
    parser.add_argument("--hop-length", type=int, default=512)
    parser.add_argument("--n-mels", type=int, default=96)
    parser.add_argument("--hidden-size", type=int, default=192)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    device = resolve_device(args.device)
    audio_config = AudioConfig(
        sample_rate=args.sample_rate,
        n_fft=args.n_fft,
        hop_length=args.hop_length,
        n_mels=args.n_mels,
    )
    dataset = ChartAudioDataset(
        charts_path=args.charts,
        audio_manifest_path=args.audio_manifest,
        audio_config=audio_config,
        segment_frames=args.segment_frames,
        samples_per_epoch=args.samples_per_epoch,
    )
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False)

    model = ChartGenerator(n_mels=args.n_mels, hidden_size=args.hidden_size).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([8, 8, 8, 8, 3, 3, 3, 3], device=device))

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        for features, labels in loader:
            features = features.to(device)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(features)
            loss = loss_fn(logits, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += float(loss.detach().cpu())

        avg_loss = total_loss / max(1, len(loader))
        print(f"epoch={epoch} loss={avg_loss:.5f}")
        save_checkpoint(args.output, model, audio_config, args, epoch, avg_loss)

    return 0


def resolve_device(device: str) -> torch.device:
    if device != "auto":
        return torch.device(device)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def save_checkpoint(
    path: Path,
    model: ChartGenerator,
    audio_config: AudioConfig,
    args: argparse.Namespace,
    epoch: int,
    loss: float,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state": model.state_dict(),
            "model_config": {
                "n_mels": args.n_mels,
                "hidden_size": args.hidden_size,
                "output_size": 8,
            },
            "audio_config": {
                "sample_rate": audio_config.sample_rate,
                "n_fft": audio_config.n_fft,
                "hop_length": audio_config.hop_length,
                "n_mels": audio_config.n_mels,
                "frame_seconds": audio_config.frame_seconds,
            },
            "epoch": epoch,
            "loss": loss,
        },
        path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
