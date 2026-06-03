#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rhythm_ai.audio import audio_to_features
from rhythm_ai.model import ChartGenerator
from rhythm_ai.postprocess import logits_to_chart_events


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a DJMAX-style 4B chart.")
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--bpm", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tap-threshold", type=float, default=0.45)
    parser.add_argument("--hold-threshold", type=float, default=0.50)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    device = resolve_device(args.device)
    checkpoint = torch.load(args.checkpoint, map_location=device)
    model = ChartGenerator(**checkpoint["model_config"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    audio_config = checkpoint["audio_config"]
    features = audio_to_features(
        args.audio,
        sample_rate=audio_config["sample_rate"],
        n_fft=audio_config["n_fft"],
        hop_length=audio_config["hop_length"],
        n_mels=audio_config["n_mels"],
    ).unsqueeze(0)

    with torch.no_grad():
        logits = model(features.to(device)).squeeze(0).cpu().numpy()

    events = logits_to_chart_events(
        logits,
        bpm=args.bpm,
        frame_seconds=audio_config["frame_seconds"],
        tap_threshold=args.tap_threshold,
        hold_threshold=args.hold_threshold,
    )

    chart = {
        "title": args.title,
        "mode": "4B",
        "difficulty": "AI",
        "bpm": {"min": args.bpm, "max": args.bpm},
        "noteCount": len(events),
        "events": events,
        "generator": {
            "checkpoint": str(args.checkpoint),
            "tapThreshold": args.tap_threshold,
            "holdThreshold": args.hold_threshold,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(chart, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"events: {len(events)}")
    print(f"output: {args.output}")
    return 0


def resolve_device(device: str) -> torch.device:
    if device != "auto":
        return torch.device(device)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


if __name__ == "__main__":
    raise SystemExit(main())
