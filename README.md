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

## Minimal Local Demo

This smoke test creates a copyright-free synthetic WAV and a matching 4B chart,
then runs the real manifest, training, generation, and evaluation scripts. It
does not require DJMAX audio or any external download.

Create the demo input:

```bash
python3 scripts/prepare_minimal_demo.py
```

This creates:

- `demo/audio/Minimal Demo Pulse.wav`
- `demo/data/minimal_charts.jsonl`

Build the one-song audio manifest:

```bash
python3 scripts/create_audio_manifest.py \
  --charts demo/data/minimal_charts.jsonl \
  --audio-dir demo/audio \
  --output demo/data/audio_manifest.json \
  --missing-output demo/data/missing_audio_queries.txt
```

Train a deliberately small model:

```bash
python3 scripts/train_chart_model.py \
  --charts demo/data/minimal_charts.jsonl \
  --audio-manifest demo/data/audio_manifest.json \
  --output demo/checkpoints/minimal_demo.pt \
  --epochs 2 \
  --samples-per-epoch 32 \
  --segment-frames 256 \
  --batch-size 4 \
  --hidden-size 64
```

Generate a chart:

```bash
python3 scripts/generate_chart.py \
  --checkpoint demo/checkpoints/minimal_demo.pt \
  --audio "demo/audio/Minimal Demo Pulse.wav" \
  --title "Minimal Demo Generated" \
  --difficulty NM \
  --bpm 120 \
  --tap-threshold 0.55 \
  --hold-threshold 0.55 \
  --output demo/generated/minimal_demo_4b.json
```

Evaluate it against the synthetic reference:

```bash
python3 scripts/evaluate_chart.py \
  --chart demo/generated/minimal_demo_4b.json \
  --reference-jsonl demo/data/minimal_charts.jsonl \
  --reference-title "Minimal Demo Pulse" \
  --reference-difficulty NM
```

The complete output layout is:

```text
demo/
├── audio/Minimal Demo Pulse.wav
├── data/minimal_charts.jsonl
├── data/audio_manifest.json
├── checkpoints/minimal_demo.pt
└── generated/minimal_demo_4b.json
```

This two-epoch model is only an end-to-end environment check. Its generated
chart is not expected to have production-quality patterns.

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

Resume an interrupted run:

```bash
python3 scripts/train_chart_model.py \
  --charts data/djmax_4b_charts.jsonl \
  --audio-manifest data/audio_manifest.json \
  --output checkpoints/djmax_4b_baseline.pt \
  --epochs 20 \
  --resume
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

Evaluate a generated chart:

```bash
python3 scripts/evaluate_chart.py --chart generated/example_4b.json
```

Compare it with an original chart:

```bash
python3 scripts/evaluate_chart.py \
  --chart generated/example_4b.json \
  --reference-title "#1f1e33" \
  --reference-difficulty SC
```
