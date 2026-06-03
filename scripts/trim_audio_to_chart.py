#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rhythm_ai.chart import normalize_title


AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}


@dataclass(frozen=True)
class Match:
    chart: dict
    audio_path: Path
    score: int


def load_charts(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def find_audio_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return [
        file
        for file in path.rglob("*")
        if file.is_file() and file.suffix.casefold() in AUDIO_EXTENSIONS
    ]


def chart_end_seconds(chart: dict, *, end_source: str, tail_padding: float) -> float:
    if end_source == "playtime":
        playtime = chart.get("playtimeSeconds")
        if playtime:
            return float(playtime) + tail_padding

    bpm = float(chart["bpm"]["max"] or chart["bpm"]["min"])
    last_beat = max(float(event.get("endBeat", event["beat"])) for event in chart["events"])
    return last_beat * 60.0 / bpm + tail_padding


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def trim_audio(input_path: Path, output_path: Path, duration: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-t",
            f"{duration:.6f}",
            "-vn",
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def copy_or_convert_audio(input_path: Path, output_path: Path, duration: float) -> None:
    if input_path.suffix.casefold() == ".wav":
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
        return
    trim_audio(input_path, output_path, duration)


def searchable_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    replacements = {
        "ただいま配信chu": "streaming rn chu",
        "twins stroke": "twin stroke",
        "spacial": "special",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def searchable_key(text: str) -> str:
    return normalize_title(searchable_text(text))


def searchable_tokens(text: str) -> set[str]:
    return {
        normalize_title(token)
        for token in re.split(r"[^0-9a-zA-Z가-힣ぁ-ゟ゠-ヿ一-龯]+", searchable_text(text))
        if normalize_title(token)
    }


def best_chart_match(audio_path: Path, charts: list[dict]) -> Match | None:
    audio_key = searchable_key(audio_path.stem)
    audio_tokens = searchable_tokens(audio_path.stem)
    best: Match | None = None
    for chart in charts:
        title = chart["title"]
        title_key = searchable_key(title)
        if not title_key:
            continue

        score = 0
        if len(title_key) >= 3 and title_key in audio_key:
            score += len(title_key) * 4
        elif len(title_key) < 3 and title_key in audio_tokens:
            score += 20
        else:
            title_tokens = {token for token in searchable_tokens(title) if len(token) >= 3}
            if not title_tokens:
                continue
            matched_tokens = {token for token in title_tokens if token in audio_key}
            coverage = len(matched_tokens) / len(title_tokens)
            if coverage < 0.6:
                continue
            score += sum(len(token) for token in matched_tokens) * 3

        mode = chart.get("mode", "")
        difficulty = chart.get("difficulty", "")
        if searchable_key(mode) in audio_key:
            score += 10
        if searchable_key(difficulty) in audio_key:
            score += 10
        if best is None or score > best.score:
            best = Match(chart=chart, audio_path=audio_path, score=score)
    return best


def output_path_for(input_path: Path, input_root: Path, output_dir: Path) -> Path:
    if input_root.is_file():
        relative = input_path.name
    else:
        relative = input_path.relative_to(input_root)
    return output_dir / relative.with_suffix(".wav")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trim local audio files to their matched chart end time."
    )
    parser.add_argument("--charts", default="data/djmax_4b_charts.jsonl", type=Path)
    parser.add_argument("--audio", default="audio/djmax", type=Path)
    parser.add_argument("--output-dir", default="audio/djmax_trimmed", type=Path)
    parser.add_argument(
        "--end-source",
        choices=["last-event", "playtime"],
        default="last-event",
        help="use the last note/hold end or the site playtime as trim target",
    )
    parser.add_argument("--tail-padding", type=float, default=2.0)
    parser.add_argument(
        "--min-trim-seconds",
        type=float,
        default=0.5,
        help="skip files whose tail is shorter than this",
    )
    parser.add_argument(
        "--copy-skipped",
        action="store_true",
        help="copy files that do not need trimming into the output directory",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    charts = load_charts(args.charts)
    audio_files = find_audio_files(args.audio)
    if not audio_files:
        print(f"no audio files found: {args.audio}", file=sys.stderr)
        return 1

    processed = 0
    skipped = 0
    unmatched = 0
    for audio_path in audio_files:
        match = best_chart_match(audio_path, charts)
        if match is None:
            unmatched += 1
            print(f"unmatched: {audio_path}")
            continue

        original_duration = ffprobe_duration(audio_path)
        target_duration = chart_end_seconds(
            match.chart,
            end_source=args.end_source,
            tail_padding=args.tail_padding,
        )
        target_duration = min(target_duration, original_duration)
        tail_seconds = original_duration - target_duration
        output_path = output_path_for(audio_path, args.audio, args.output_dir)

        if tail_seconds < args.min_trim_seconds:
            skipped += 1
            action = "copy" if args.copy_skipped else "skip"
            print(
                f"{action}: {audio_path} -> {output_path} "
                f"tail={tail_seconds:.3f}s "
                f"matched={match.chart['title']} {match.chart['mode']} {match.chart['difficulty']}"
            )
            if args.copy_skipped and not args.dry_run:
                copy_or_convert_audio(audio_path, output_path, original_duration)
            continue

        processed += 1
        print(
            f"trim: {audio_path} -> {output_path} "
            f"{original_duration:.3f}s -> {target_duration:.3f}s "
            f"cut={tail_seconds:.3f}s "
            f"matched={match.chart['title']} {match.chart['mode']} {match.chart['difficulty']}"
        )
        if not args.dry_run:
            trim_audio(audio_path, output_path, target_duration)

    print(f"processed: {processed}")
    print(f"skipped: {skipped}")
    print(f"unmatched: {unmatched}")
    return 0 if unmatched == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
