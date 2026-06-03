#!/usr/bin/env python3
"""Crawl and parse DJMAX charts rendered by ez2pattern.kr.

The site stores charts as server-rendered HTML/CSS, not as images. This script
collects chart links from a freestyle list page and converts each chart DOM into
beat-based note events.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
from dataclasses import asdict, dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen


BASE_URL = "https://ez2pattern.kr"
DEFAULT_LIST_URL = f"{BASE_URL}/djmax/freestyle/4B"
DIFFICULTY_ORDER = ("NM", "HD", "MX", "SC")
BAR_HEIGHT_PX = 240.0
BEAT_HEIGHT_PX = 60.0


@dataclass(frozen=True)
class ChartLink:
    url: str
    song_slug: str
    song_name: str
    mode: str
    difficulty: str
    page: int


@dataclass
class RawNote:
    lane: str
    is_long: bool
    y: float
    height: float | None


@dataclass
class Bar:
    number: int
    notes: list[RawNote]


class Ez2PatternError(RuntimeError):
    pass


class ChartDomParser(HTMLParser):
    """Small HTML parser for the chart output DOM."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.bars: list[Bar] = []
        self._current_bar: Bar | None = None
        self._bar_depth = 0
        self._in_bar_number = False
        self._in_bar_number_span = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = attr.get("class", "").split()

        if (
            self._current_bar is None
            and tag == "div"
            and "bar" in classes
            and "empty" not in classes
        ):
            self._current_bar = Bar(number=0, notes=[])
            self._bar_depth = 1
            return

        if self._current_bar is None:
            return

        if tag == "div":
            self._bar_depth += 1
            if "bar-number" in classes:
                self._in_bar_number = True
            if "note" in classes:
                note = self._parse_note(classes, attr.get("style", ""))
                if note is not None:
                    self._current_bar.notes.append(note)
        elif tag == "span" and self._in_bar_number:
            self._in_bar_number_span = True

    def handle_endtag(self, tag: str) -> None:
        if self._current_bar is None:
            return

        if tag == "span" and self._in_bar_number_span:
            self._in_bar_number_span = False
        if tag != "div":
            return

        self._bar_depth -= 1
        if self._bar_depth == 0:
            if self._current_bar.number:
                self.bars.append(self._current_bar)
            self._current_bar = None
            self._in_bar_number = False

    def handle_data(self, data: str) -> None:
        if self._current_bar is None or not self._in_bar_number_span:
            return
        text = data.strip()
        if text.isdigit():
            self._current_bar.number = int(text)

    @staticmethod
    def _parse_note(classes: list[str], style: str) -> RawNote | None:
        lane = None
        for class_name in classes:
            if class_name.startswith("note-"):
                lane = class_name.removeprefix("note-")
                break
        if lane is None:
            return None

        y_match = re.search(r"margin-top\s*:\s*calc\(([0-9.]+)px", style)
        if y_match is None:
            return None

        height_match = re.search(r"height\s*:\s*calc\(([0-9.]+)px", style)
        return RawNote(
            lane=lane,
            is_long="long" in classes,
            y=float(y_match.group(1)),
            height=float(height_match.group(1)) if height_match else None,
        )


def fetch_text(url: str, *, timeout: float = 30.0, insecure: bool = False) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; rhythm-dataset-parser/0.1; "
                "+https://ez2pattern.kr)"
            )
        },
    )
    context = ssl._create_unverified_context() if insecure else None
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            return response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise Ez2PatternError(f"failed to fetch {url}: {exc}") from exc


def page_url(list_url: str, page: int) -> str:
    if page <= 1:
        return list_url
    sep = "&" if "?" in list_url else "?"
    return f"{list_url}{sep}page={page}"


def extract_max_page(html: str) -> int:
    pages = [int(page) for page in re.findall(r'data-page="(\d+)"', html)]
    return max(pages) if pages else 1


def extract_chart_links(html: str, page: int, base_url: str = BASE_URL) -> list[ChartLink]:
    seen: set[str] = set()
    links: list[ChartLink] = []
    pattern = re.compile(
        r'href=["\'](?P<href>/djmax/chart/(?P<song>.*?)/(?P<mode>\d+B)/'
        r'(?P<diff>NM|HD|MX|SC)(?:\?[^"\']*)?)["\']'
    )
    for match in pattern.finditer(html):
        href = unescape(match.group("href"))
        absolute_url = urljoin(base_url, href)
        if absolute_url in seen:
            continue
        seen.add(absolute_url)

        song_slug = unquote(unescape(match.group("song")))
        links.append(
            ChartLink(
                url=absolute_url,
                song_slug=song_slug,
                song_name=song_slug,
                mode=match.group("mode"),
                difficulty=match.group("diff"),
                page=page,
            )
        )
    return links


def collect_chart_links(
    list_url: str,
    *,
    max_pages: int | None = None,
    delay_seconds: float = 0.25,
    insecure: bool = False,
) -> list[ChartLink]:
    first_html = fetch_text(page_url(list_url, 1), insecure=insecure)
    discovered_max_page = extract_max_page(first_html)
    last_page = min(max_pages or discovered_max_page, discovered_max_page)

    all_links = extract_chart_links(first_html, 1)
    for page in range(2, last_page + 1):
        time.sleep(delay_seconds)
        html = fetch_text(page_url(list_url, page), insecure=insecure)
        all_links.extend(extract_chart_links(html, page))

    return sort_chart_links(dedupe_chart_links(all_links))


def dedupe_chart_links(links: Iterable[ChartLink]) -> list[ChartLink]:
    by_url: dict[str, ChartLink] = {}
    for link in links:
        by_url.setdefault(link.url, link)
    return list(by_url.values())


def sort_chart_links(links: Iterable[ChartLink]) -> list[ChartLink]:
    return sorted(
        links,
        key=lambda link: (
            link.page,
            link.song_name.casefold(),
            DIFFICULTY_ORDER.index(link.difficulty)
            if link.difficulty in DIFFICULTY_ORDER
            else len(DIFFICULTY_ORDER),
        ),
    )


def extract_script_float_pair(html: str, function_name: str) -> tuple[float, float] | None:
    match = re.search(
        rf"{re.escape(function_name)}\(([0-9.]+)\s*,\s*([0-9.]+)\)",
        html,
    )
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def extract_first_number_after_label(html: str, label: str) -> int | None:
    match = re.search(
        rf"{re.escape(label)}</td>\s*<td[^>]*>\s*([0-9,]+)",
        html,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def extract_playtime_seconds(html: str) -> int | None:
    match = re.search(r"Playtime</td>\s*<td[^>]*>\s*([0-9]+):([0-9]{2})", html)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def extract_title_from_html(html: str, fallback: str) -> str:
    match = re.search(r'<td id="song-title"[^>]*>\s*(.*?)\s*</td>', html, re.DOTALL)
    if match:
        return unescape(strip_tags(match.group(1))).strip() or fallback

    og_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    if og_match:
        title = unescape(og_match.group(1)).strip()
        return re.sub(r"\s+\d+B\s+(NM|HD|MX|SC)\s+-\s+EZ2PATTERN$", "", title)
    return fallback


def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def extract_chart_identity(url: str) -> tuple[str, str, str]:
    path_parts = urlparse(url).path.split("/")
    try:
        chart_index = path_parts.index("chart")
        song_slug = unquote(path_parts[chart_index + 1])
        mode = path_parts[chart_index + 2]
        difficulty = path_parts[chart_index + 3]
    except (ValueError, IndexError) as exc:
        raise Ez2PatternError(f"not a chart URL: {url}") from exc
    return song_slug, mode, difficulty


def extract_key_order(html: str, mode: str) -> str:
    match = re.search(r'let\s+gKeyOrder\s*=\s*"([^"]+)"', html)
    if match:
        return match.group(1).upper()

    key_count = int(mode.replace("B", ""))
    return "".join(str(i) for i in range(1, key_count + 1)) + "AB"


def beat_for_y(bar_number: int, y: float) -> float:
    return (bar_number - 1) * 4 + (BAR_HEIGHT_PX - y) / BEAT_HEIGHT_PX


def round_beat(value: float) -> float:
    return round(value + 0.0, 6)


def parse_chart_html(html: str, source_url: str) -> dict:
    song_slug, mode, difficulty = extract_chart_identity(source_url)
    key_order = extract_key_order(html, mode)
    valid_lanes = set(key_order)

    parser = ChartDomParser()
    parser.feed(html)
    if not parser.bars:
        raise Ez2PatternError(f"no chart bars found: {source_url}")

    bpm_pair = extract_script_float_pair(html, "printBPM")
    events: list[dict] = []
    tap_keys: set[tuple[str, float]] = set()
    ignored_notes: list[dict] = []

    for bar in parser.bars:
        for note in bar.notes:
            if note.lane not in valid_lanes:
                ignored_notes.append(
                    {
                        "bar": bar.number,
                        "lane": note.lane,
                        "type": "long" if note.is_long else "tap",
                        "y": note.y,
                    }
                )
                continue
            if note.is_long:
                continue
            beat = round_beat(beat_for_y(bar.number, note.y))
            tap_keys.add((note.lane, beat))
            events.append(
                {
                    "type": "tap",
                    "beat": beat,
                    "lane": note.lane,
                    "bar": bar.number,
                    "y": note.y,
                }
            )

    consumed_hold_heads: set[tuple[str, float]] = set()
    for bar in parser.bars:
        for note in bar.notes:
            if not note.is_long or note.lane not in valid_lanes or note.height is None:
                continue
            head_y = note.y + note.height
            start_beat = round_beat(beat_for_y(bar.number, head_y))
            head_key = (note.lane, start_beat)
            if head_key in tap_keys:
                consumed_hold_heads.add(head_key)

            end_beat = round_beat(beat_for_y(bar.number, note.y))
            events.append(
                {
                    "type": "hold",
                    "beat": start_beat,
                    "endBeat": end_beat,
                    "durationBeats": round_beat(end_beat - start_beat),
                    "lane": note.lane,
                    "bar": bar.number,
                    "y": note.y,
                    "height": note.height,
                    "hasHead": head_key in tap_keys,
                }
            )

    if consumed_hold_heads:
        events = [
            event
            for event in events
            if not (
                event["type"] == "tap"
                and (event["lane"], event["beat"]) in consumed_hold_heads
            )
        ]

    events.sort(
        key=lambda event: (
            event["beat"],
            str(event["lane"]),
            0 if event["type"] == "hold" else 1,
        )
    )

    note_count = sum(1 for event in events if event["type"] == "tap") + sum(
        1 for event in events if event["type"] == "hold"
    )

    return {
        "source": {
            "site": "EZ2PATTERN",
            "url": source_url,
            "songSlug": song_slug,
        },
        "title": extract_title_from_html(html, song_slug),
        "mode": mode,
        "difficulty": difficulty,
        "keyOrder": key_order,
        "validLanes": list(key_order),
        "bpm": {
            "min": bpm_pair[0] if bpm_pair else None,
            "max": bpm_pair[1] if bpm_pair else None,
        },
        "level": extract_first_number_after_label(html, "Level"),
        "displayedNotes": extract_first_number_after_label(html, "Notes"),
        "playtimeSeconds": extract_playtime_seconds(html),
        "bars": len(parser.bars),
        "noteCount": note_count,
        "tapCount": sum(1 for event in events if event["type"] == "tap"),
        "holdCount": sum(1 for event in events if event["type"] == "hold"),
        "ignoredNotes": ignored_notes,
        "events": events,
    }


def parse_chart_url(url: str, *, insecure: bool = False) -> dict:
    return parse_chart_html(fetch_text(url, insecure=insecure), url)


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            file.write("\n")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def crawl(args: argparse.Namespace) -> int:
    links = collect_chart_links(
        args.list_url,
        max_pages=args.max_pages,
        delay_seconds=args.delay,
        insecure=args.insecure,
    )
    if args.limit is not None:
        links = links[: args.limit]

    charts: list[dict] = []
    failures: list[dict] = []
    for index, link in enumerate(links, start=1):
        print(
            f"[{index}/{len(links)}] {link.song_name} {link.mode} {link.difficulty}",
            file=sys.stderr,
        )
        try:
            charts.append(parse_chart_url(link.url, insecure=args.insecure))
        except Ez2PatternError as exc:
            failures.append({**asdict(link), "error": str(exc)})
        time.sleep(args.delay)

    write_jsonl(args.output_jsonl, charts)
    write_json(
        args.output_index,
        {
            "listUrl": args.list_url,
            "chartCount": len(charts),
            "failureCount": len(failures),
            "failures": failures,
            "charts": [
                {
                    "title": chart["title"],
                    "mode": chart["mode"],
                    "difficulty": chart["difficulty"],
                    "url": chart["source"]["url"],
                    "noteCount": chart["noteCount"],
                    "displayedNotes": chart["displayedNotes"],
                    "ignoredNotes": chart["ignoredNotes"],
                }
                for chart in charts
            ],
        },
    )
    return 1 if failures else 0


def parse_one(args: argparse.Namespace) -> int:
    chart = parse_chart_url(args.chart_url, insecure=args.insecure)
    print(json.dumps(chart, ensure_ascii=False, indent=2))
    return 0


def list_links(args: argparse.Namespace) -> int:
    links = collect_chart_links(
        args.list_url,
        max_pages=args.max_pages,
        delay_seconds=args.delay,
        insecure=args.insecure,
    )
    if args.limit is not None:
        links = links[: args.limit]
    for link in links:
        print(json.dumps(asdict(link), ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_parser = subparsers.add_parser("crawl", help="crawl list pages and parse charts")
    crawl_parser.add_argument("--list-url", default=DEFAULT_LIST_URL)
    crawl_parser.add_argument("--max-pages", type=int, default=None)
    crawl_parser.add_argument("--limit", type=int, default=None)
    crawl_parser.add_argument("--delay", type=float, default=0.25)
    crawl_parser.add_argument(
        "--insecure",
        action="store_true",
        help="disable TLS certificate verification if local Python lacks CA roots",
    )
    crawl_parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=Path("data/djmax_4b_charts.jsonl"),
    )
    crawl_parser.add_argument(
        "--output-index",
        type=Path,
        default=Path("data/djmax_4b_index.json"),
    )
    crawl_parser.set_defaults(func=crawl)

    one_parser = subparsers.add_parser("parse-one", help="parse a single chart URL")
    one_parser.add_argument("chart_url")
    one_parser.add_argument(
        "--insecure",
        action="store_true",
        help="disable TLS certificate verification if local Python lacks CA roots",
    )
    one_parser.set_defaults(func=parse_one)

    links_parser = subparsers.add_parser("list-links", help="print discovered chart links")
    links_parser.add_argument("--list-url", default=DEFAULT_LIST_URL)
    links_parser.add_argument("--max-pages", type=int, default=None)
    links_parser.add_argument("--limit", type=int, default=None)
    links_parser.add_argument("--delay", type=float, default=0.25)
    links_parser.add_argument(
        "--insecure",
        action="store_true",
        help="disable TLS certificate verification if local Python lacks CA roots",
    )
    links_parser.set_defaults(func=list_links)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
