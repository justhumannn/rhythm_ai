# Rhythm Dataset Tools

Utilities for collecting rhythm-game chart data.

한국어 문서는 [README.ko.md](README.ko.md)를 참고하세요.

## EZ2PATTERN DJMAX Parser

EZ2PATTERN renders DJMAX charts as HTML/CSS DOM nodes. The parser in
`scripts/ez2pattern_djmax_parser.py` crawls the 4B freestyle list and converts
each chart page into beat-based JSON events.

### Crawl 4B Charts

```bash
python3 scripts/ez2pattern_djmax_parser.py crawl --insecure
```

Outputs:

- `data/djmax_4b_charts.jsonl`: one parsed chart per line
- `data/djmax_4b_index.json`: compact crawl summary and failures

`--insecure` is only needed when the local Python install cannot verify the
site TLS certificate.

### Parse One Chart

```bash
python3 scripts/ez2pattern_djmax_parser.py parse-one \
  'https://ez2pattern.kr/djmax/chart/%EC%97%BC%EB%9D%BC/4B/MX' \
  --insecure
```

### Output Event Shape

Tap note:

```json
{"type":"tap","beat":2.0,"lane":"1","bar":1,"y":120.0}
```

Hold note:

```json
{"type":"hold","beat":18.0,"endBeat":18.75,"durationBeats":0.75,"lane":"3"}
```

Timing is derived from the site layout:

- 1 bar = 240 px
- 1 beat = 60 px
- `beat = (bar - 1) * 4 + (240 - y) / 60`

## Baseline Chart Generation Model

The baseline model in `rhythm_ai/` trains a frame-wise 4B chart generator from
local audio files and parsed chart JSONL.

The project does not include an automatic YouTube downloader. Use local audio
files that you have the right to process.

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Create an audio manifest from local files:

```bash
python3 scripts/create_audio_manifest.py \
  --charts data/djmax_4b_charts.jsonl \
  --audio-dir audio/djmax \
  --output data/audio_manifest.json \
  --missing-output data/missing_audio_queries.txt
```

Train:

```bash
python3 scripts/train_chart_model.py \
  --charts data/djmax_4b_charts.jsonl \
  --audio-manifest data/audio_manifest.json \
  --output checkpoints/djmax_4b_baseline.pt \
  --epochs 20
```

Generate a chart:

```bash
python3 scripts/generate_chart.py \
  --checkpoint checkpoints/djmax_4b_baseline.pt \
  --audio audio/example.wav \
  --title "example" \
  --bpm 132 \
  --output generated/example_4b.json
```
