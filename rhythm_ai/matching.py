from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from rhythm_ai.chart import normalize_title


@dataclass(frozen=True)
class ChartMatch:
    chart: dict
    audio_path: Path
    score: int


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


def chart_audio_match_score(chart: dict, audio_path: Path) -> int | None:
    audio_key = searchable_key(audio_path.stem)
    audio_tokens = searchable_tokens(audio_path.stem)
    title = chart["title"]
    title_key = searchable_key(title)
    if not title_key:
        return None

    score = 0
    if len(title_key) >= 3 and title_key in audio_key:
        score += len(title_key) * 4
    elif len(title_key) < 3 and title_key in audio_tokens:
        score += 20
    else:
        title_tokens = {token for token in searchable_tokens(title) if len(token) >= 3}
        if not title_tokens:
            return None
        matched_tokens = {token for token in title_tokens if token in audio_key}
        coverage = len(matched_tokens) / len(title_tokens)
        if coverage < 0.6:
            return None
        score += sum(len(token) for token in matched_tokens) * 3

    mode = chart.get("mode", "")
    difficulty = chart.get("difficulty", "")
    if searchable_key(mode) in audio_key:
        score += 10
    if searchable_key(difficulty) in audio_key:
        score += 10
    return score


def best_chart_match(audio_path: Path, charts: list[dict]) -> ChartMatch | None:
    best: ChartMatch | None = None
    for chart in charts:
        score = chart_audio_match_score(chart, audio_path)
        if score is None:
            continue
        if best is None or score > best.score:
            best = ChartMatch(chart=chart, audio_path=audio_path, score=score)
    return best
