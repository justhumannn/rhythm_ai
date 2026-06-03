#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import ssl
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


YOUTUBE_SEARCH_URL = "https://www.youtube.com/results?search_query={query}"
YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"


@dataclass
class SearchResult:
    query: str
    url: str | None
    video_id: str | None
    alternatives: list[str]
    error: str | None = None


def fetch_text(url: str, *, timeout: float = 30.0, insecure: bool = False) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    context = ssl._create_unverified_context() if insecure else None
    with urlopen(request, timeout=timeout, context=context) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_video_ids(html: str, *, limit: int) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    patterns = [
        r'"videoId":"([a-zA-Z0-9_-]{11})"',
        r"watch\?v=([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        for video_id in re.findall(pattern, html):
            if video_id in seen:
                continue
            seen.add(video_id)
            ids.append(video_id)
            if len(ids) >= limit:
                return ids
    return ids


def search_query(
    query: str,
    *,
    alternatives: int,
    timeout: float,
    insecure: bool,
) -> SearchResult:
    search_url = YOUTUBE_SEARCH_URL.format(query=quote_plus(query))
    try:
        html = fetch_text(search_url, timeout=timeout, insecure=insecure)
        video_ids = extract_video_ids(html, limit=alternatives)
        if not video_ids:
            return SearchResult(
                query=query,
                url=None,
                video_id=None,
                alternatives=[],
                error="no video candidates found",
            )
        urls = [YOUTUBE_WATCH_URL.format(video_id=video_id) for video_id in video_ids]
        return SearchResult(
            query=query,
            url=urls[0],
            video_id=video_ids[0],
            alternatives=urls[1:],
        )
    except (HTTPError, URLError, TimeoutError) as exc:
        return SearchResult(
            query=query,
            url=None,
            video_id=None,
            alternatives=[],
            error=str(exc),
        )


def read_queries(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, results: list[SearchResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, results: list[SearchResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["query", "url", "video_id", "alternatives", "error"],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "query": result.query,
                    "url": result.url or "",
                    "video_id": result.video_id or "",
                    "alternatives": " ".join(result.alternatives),
                    "error": result.error or "",
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search YouTube links for queries from a text file."
    )
    parser.add_argument("--queries", default="data/missing_audio_queries.txt", type=Path)
    parser.add_argument("--output-json", default="data/youtube_search_results.json", type=Path)
    parser.add_argument("--output-csv", default="data/youtube_search_results.csv", type=Path)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=0.75)
    parser.add_argument("--alternatives", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="disable TLS certificate verification if local Python lacks CA roots",
    )
    args = parser.parse_args()

    queries = read_queries(args.queries)
    if args.limit is not None:
        queries = queries[: args.limit]

    results: list[SearchResult] = []
    for index, query in enumerate(queries, start=1):
        print(f"[{index}/{len(queries)}] {query}", file=sys.stderr)
        results.append(
            search_query(
                query,
                alternatives=args.alternatives,
                timeout=args.timeout,
                insecure=args.insecure,
            )
        )
        if index < len(queries):
            time.sleep(args.delay)

    write_json(args.output_json, results)
    write_csv(args.output_csv, results)
    success_count = sum(1 for result in results if result.url)
    print(f"success: {success_count}/{len(results)}")
    print(f"json: {args.output_json}")
    print(f"csv: {args.output_csv}")
    return 0 if success_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
