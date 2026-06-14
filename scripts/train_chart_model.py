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


TAP_METRIC_THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a DJMAX 4B chart model.")
    parser.add_argument("--charts", default="data/djmax_4b_charts.jsonl")
    parser.add_argument("--audio-manifest", required=True)
    parser.add_argument("--output", default="checkpoints/djmax_4b_conditional.pt", type=Path)
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
    parser.add_argument("--tap-radius-frames", type=int, default=1)
    parser.add_argument(
        "--tap-pos-weight",
        type=float,
        default=3.0,
        help="positive-class loss weight for tap lanes; lower values reduce false taps",
    )
    parser.add_argument(
        "--hold-pos-weight",
        type=float,
        default=3.0,
        help="positive-class loss weight for hold lanes",
    )
    parser.add_argument(
        "--metric-tap-threshold",
        type=float,
        default=0.5,
        help="tap probability threshold used only for training metrics",
    )
    parser.add_argument(
        "--metric-hold-threshold",
        type=float,
        default=0.5,
        help="hold probability threshold used only for training metrics",
    )
    parser.add_argument(
        "--init-from",
        type=Path,
        help="initialize shared weights from an older checkpoint without resuming its optimizer",
    )
    parser.add_argument(
        "--unbalanced-difficulty",
        action="store_true",
        help="sample charts uniformly instead of balancing NM/HD/MX/SC",
    )
    parser.add_argument(
        "--require-training-eligible",
        action="store_true",
        help="only use rows marked training_eligible in an aligned manifest",
    )
    parser.add_argument(
        "--exclude-gameplay-audio",
        action="store_true",
        help="exclude audio filenames identified as 4B/5B/6B/8B gameplay videos",
    )
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume from --output if the checkpoint exists",
    )
    args = parser.parse_args()
    if args.tap_pos_weight <= 0 or args.hold_pos_weight <= 0:
        parser.error("positive-class weights must be greater than zero")
    if not 0 < args.metric_tap_threshold < 1:
        parser.error("--metric-tap-threshold must be between 0 and 1")
    if not 0 < args.metric_hold_threshold < 1:
        parser.error("--metric-hold-threshold must be between 0 and 1")

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
        balanced_difficulty=not args.unbalanced_difficulty,
        tap_radius_frames=args.tap_radius_frames,
        require_training_eligible=args.require_training_eligible,
        exclude_gameplay_audio=args.exclude_gameplay_audio,
    )
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False)

    checkpoint_config = checkpoint_model_config(args.output, device) if args.resume else None
    model_config = checkpoint_config or {
        "n_mels": args.n_mels,
        "hidden_size": args.hidden_size,
        "output_size": 8,
        "difficulty_count": 4,
    }
    model = ChartGenerator(**model_config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    loss_fn = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor(
            [args.tap_pos_weight] * 4 + [args.hold_pos_weight] * 4,
            device=device,
        )
    )

    start_epoch = 1
    if args.resume and args.output.exists():
        if model.difficulty_count == 0:
            raise SystemExit(
                "cannot resume legacy unconditioned checkpoint; "
                "use a new --output with --init-from checkpoints/djmax_4b_baseline.pt"
            )
        start_epoch = load_checkpoint(args.output, model, optimizer, device) + 1
        for param_group in optimizer.param_groups:
            param_group["lr"] = args.learning_rate
        print(f"resuming from epoch={start_epoch}")
    elif args.init_from:
        initialize_from_checkpoint(args.init_from, model, device)

    if start_epoch > args.epochs:
        print(f"checkpoint already reached epoch={start_epoch - 1}; target epochs={args.epochs}")
        return 0

    for epoch in range(start_epoch, args.epochs + 1):
        model.train()
        total_loss = 0.0
        tap_counts = BinaryCounts()
        tap_sweep_counts = {
            threshold: BinaryCounts() for threshold in TAP_METRIC_THRESHOLDS
        }
        hold_counts = BinaryCounts()
        for features, labels, difficulty in loader:
            features = features.to(device)
            labels = labels.to(device)
            difficulty = difficulty.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(features, difficulty)
            loss = loss_fn(logits, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += float(loss.detach().cpu())
            with torch.no_grad():
                probabilities = torch.sigmoid(logits)
                targets = labels >= 0.5
                tap_counts.update(
                    probabilities[..., :4] >= args.metric_tap_threshold,
                    targets[..., :4],
                )
                for threshold, counts in tap_sweep_counts.items():
                    counts.update(
                        probabilities[..., :4] >= threshold,
                        targets[..., :4],
                    )
                hold_counts.update(
                    probabilities[..., 4:] >= args.metric_hold_threshold,
                    targets[..., 4:],
                )

        avg_loss = total_loss / max(1, len(loader))
        best_tap_threshold, best_tap_counts = max(
            tap_sweep_counts.items(),
            key=lambda item: item[1].f1(),
        )
        print(
            f"epoch={epoch} loss={avg_loss:.5f} "
            f"tap_f1={tap_counts.f1():.4f} tap_p={tap_counts.precision():.4f} "
            f"tap_r={tap_counts.recall():.4f} "
            f"tap_best_f1={best_tap_counts.f1():.4f}@{best_tap_threshold:.2f} "
            f"hold_f1={hold_counts.f1():.4f} hold_p={hold_counts.precision():.4f} "
            f"hold_r={hold_counts.recall():.4f} "
            f"thresholds={args.metric_tap_threshold:.2f}/{args.metric_hold_threshold:.2f}"
        )
        save_checkpoint(args.output, model, optimizer, audio_config, args, epoch, avg_loss)

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
    optimizer: torch.optim.Optimizer,
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
                "difficulty_count": model.difficulty_count,
            },
            "optimizer_state": optimizer.state_dict(),
            "audio_config": {
                "sample_rate": audio_config.sample_rate,
                "n_fft": audio_config.n_fft,
                "hop_length": audio_config.hop_length,
                "n_mels": audio_config.n_mels,
                "frame_seconds": audio_config.frame_seconds,
            },
            "epoch": epoch,
            "loss": loss,
            "training_config": {
                "tap_radius_frames": args.tap_radius_frames,
                "balanced_difficulty": not args.unbalanced_difficulty,
                "tap_pos_weight": args.tap_pos_weight,
                "hold_pos_weight": args.hold_pos_weight,
                "metric_tap_threshold": args.metric_tap_threshold,
                "metric_hold_threshold": args.metric_hold_threshold,
                "require_training_eligible": args.require_training_eligible,
                "exclude_gameplay_audio": args.exclude_gameplay_audio,
            },
        },
        path,
    )


def load_checkpoint(
    path: Path,
    model: ChartGenerator,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> int:
    checkpoint = torch.load(path, map_location=device)
    model.load_state_dict(checkpoint["model_state"])
    optimizer_state = checkpoint.get("optimizer_state")
    if optimizer_state is not None:
        optimizer.load_state_dict(optimizer_state)
    else:
        print("checkpoint has no optimizer_state; resuming with a fresh optimizer")
    return int(checkpoint.get("epoch", 0))


def checkpoint_model_config(path: Path, device: torch.device) -> dict | None:
    if not path.exists():
        return None
    checkpoint = torch.load(path, map_location=device)
    return checkpoint.get("model_config")


def initialize_from_checkpoint(
    path: Path,
    model: ChartGenerator,
    device: torch.device,
) -> None:
    checkpoint = torch.load(path, map_location=device)
    state = checkpoint["model_state"]
    compatible = {
        key: value
        for key, value in state.items()
        if key in model.state_dict() and model.state_dict()[key].shape == value.shape
    }
    result = model.load_state_dict(compatible, strict=False)
    print(
        f"initialized from {path}: loaded={len(compatible)} "
        f"missing={len(result.missing_keys)} unexpected={len(result.unexpected_keys)}"
    )


class BinaryCounts:
    def __init__(self) -> None:
        self.tp = 0
        self.fp = 0
        self.fn = 0

    def update(self, predictions: torch.Tensor, targets: torch.Tensor) -> None:
        self.tp += int((predictions & targets).sum().item())
        self.fp += int((predictions & ~targets).sum().item())
        self.fn += int((~predictions & targets).sum().item())

    def precision(self) -> float:
        return self.tp / max(1, self.tp + self.fp)

    def recall(self) -> float:
        return self.tp / max(1, self.tp + self.fn)

    def f1(self) -> float:
        precision = self.precision()
        recall = self.recall()
        return 2 * precision * recall / max(1e-9, precision + recall)


if __name__ == "__main__":
    raise SystemExit(main())
