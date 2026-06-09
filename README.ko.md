# Rhythm Dataset Tools 한국어 문서

DJMAX 채보 데이터를 수집하고, 오디오와 연결해 자동 채보 생성 모델을 학습하기 위한 도구입니다.

## EZ2PATTERN DJMAX 파서

EZ2PATTERN의 DJMAX 채보는 이미지가 아니라 HTML/CSS DOM으로 렌더링됩니다.
`scripts/ez2pattern_djmax_parser.py`는 4B 프리스타일 목록을 순회하며 각 차트 페이지를 beat 기반 JSON 이벤트로 변환합니다.

### 4B 채보 수집

```bash
python3 scripts/ez2pattern_djmax_parser.py crawl --insecure
```

출력 파일:

- `data/djmax_4b_charts.jsonl`: 한 줄에 한 채보가 들어 있는 JSONL 데이터셋
- `data/djmax_4b_index.json`: 수집 요약, 실패 목록, 차트별 메타데이터

`--insecure`는 로컬 Python이 사이트 TLS 인증서를 검증하지 못할 때만 필요합니다.

### 단일 채보 파싱

```bash
python3 scripts/ez2pattern_djmax_parser.py parse-one \
  'https://ez2pattern.kr/djmax/chart/%EC%97%BC%EB%9D%BC/4B/MX' \
  --insecure
```

### 이벤트 형식

탭 노트:

```json
{"type":"tap","beat":2.0,"lane":"1","bar":1,"y":120.0}
```

롱노트:

```json
{"type":"hold","beat":18.0,"endBeat":18.75,"durationBeats":0.75,"lane":"3"}
```

시간축은 사이트의 CSS 레이아웃에서 계산합니다.

- 1마디 = 240px
- 1박 = 60px
- `beat = (bar - 1) * 4 + (240 - y) / 60`

## 자동 채보 생성 모델

`rhythm_ai/`와 `scripts/train_chart_model.py`, `scripts/generate_chart.py`는 4B 자동 채보 생성을 위한 베이스라인 학습/추론 파이프라인입니다.

모델 입력:

- 오디오 log-mel spectrogram

모델 출력:

- 프레임별 4개 레인의 `tap onset`
- 프레임별 4개 레인의 `hold active`

주의: 웹앱은 사용자가 입력한 YouTube 링크를 `yt-dlp`로 WAV 변환할 수 있습니다. 서비스 운영 시에는 저작권과 플랫폼 약관을 직접 확인해야 합니다.

### 의존성 설치

```bash
python3 -m pip install -r requirements.txt
```

### 오디오 매니페스트 만들기

로컬 음원 폴더와 채보 제목을 매칭합니다.

```bash
python3 scripts/create_audio_manifest.py \
  --charts data/djmax_4b_charts.jsonl \
  --audio-dir audio/djmax \
  --output data/audio_manifest.json \
  --missing-output data/missing_audio_queries.txt
```

`data/missing_audio_queries.txt`에는 매칭되지 않은 곡에 대해 사람이 검색할 수 있는 검색어가 저장됩니다.

### 학습

```bash
python3 scripts/train_chart_model.py \
  --charts data/djmax_4b_charts.jsonl \
  --audio-manifest data/audio_manifest.json \
  --output checkpoints/djmax_4b_baseline.pt \
  --epochs 20
```

난이도 조건을 실제 모델 입력으로 사용하는 새 모델을 학습하려면 기존 100 epoch 가중치를 초기값으로 가져와 별도 체크포인트로 시작합니다.

```bash
.venv/bin/python -B scripts/train_chart_model.py \
  --charts data/djmax_4b_charts.jsonl \
  --audio-manifest data/audio_manifest.json \
  --output checkpoints/djmax_4b_conditional.pt \
  --init-from checkpoints/djmax_4b_baseline.pt \
  --learning-rate 1e-4 \
  --epochs 40
```

이 모델을 이어서 학습할 때만 `--resume`을 사용합니다.

```bash
.venv/bin/python -B scripts/train_chart_model.py \
  --charts data/djmax_4b_charts.jsonl \
  --audio-manifest data/audio_manifest.json \
  --output checkpoints/djmax_4b_conditional.pt \
  --learning-rate 1e-4 \
  --epochs 80 \
  --resume
```

새 학습 로그의 loss는 이전 모델과 라벨 정의가 달라 직접 비교할 수 없습니다. `tap_f1`, `hold_f1`, precision, recall도 함께 확인해야 합니다.

중간에 멈춘 학습을 이어서 진행하려면:

```bash
python3 scripts/train_chart_model.py \
  --charts data/djmax_4b_charts.jsonl \
  --audio-manifest data/audio_manifest.json \
  --output checkpoints/djmax_4b_baseline.pt \
  --epochs 20 \
  --resume
```

### 새 곡 채보 생성

```bash
python3 scripts/generate_chart.py \
  --checkpoint checkpoints/djmax_4b_baseline.pt \
  --audio audio/example.wav \
  --title "example" \
  --bpm 132 \
  --output generated/example_4b.json
```

생성 결과는 beat 기반 JSON 이벤트로 저장됩니다.

후처리 숫자를 직접 조정할 수도 있습니다.

```bash
python3 scripts/generate_chart.py \
  --checkpoint checkpoints/djmax_4b_baseline.pt \
  --audio audio/example.wav \
  --title "example" \
  --bpm 132 \
  --tap-threshold 0.725 \
  --hold-threshold 0.10 \
  --tap-thresholds 0.685,0.755,0.755,0.685 \
  --min-tap-gap-seconds 0.09 \
  --min-hold-seconds 0.10 \
  --output generated/example_4b.json
```

### 후처리 숫자 자동 탐색

기준 채보가 있는 곡은 여러 임계값 조합을 자동으로 생성/평가해 가장 가까운 후보를 찾을 수 있습니다.

```bash
python3 scripts/sweep_generation_thresholds.py \
  --checkpoint checkpoints/djmax_4b_baseline.pt \
  --audio "audio/djmax_trimmed/[DJMAX RESPECT V] #1f1e33 4B SC ☆15.wav" \
  --title "#1f1e33 AI" \
  --bpm 181 \
  --reference-title "#1f1e33" \
  --reference-difficulty SC \
  --output-chart generated/hash_1f1e33_ai_sweep_best.json \
  --output-results generated/hash_1f1e33_threshold_sweep.json
```

스윕 결과 JSON에는 전체 후보의 노트 수, 홀 수, 차선 분포, 밀도 통계가 들어 있습니다. 한 곡에서 찾은 값은 출발점일 뿐이므로, 다른 곡에도 적용한 뒤 평가 스크립트로 다시 확인하는 것이 좋습니다.

### 채보 평가

생성된 단일 채보를 평가합니다.

```bash
python3 scripts/evaluate_chart.py \
  --chart generated/example_4b.json
```

원본 채보와 비교합니다.

```bash
python3 scripts/evaluate_chart.py \
  --chart generated/example_4b.json \
  --reference-title "#1f1e33" \
  --reference-difficulty SC
```

원본 데이터셋 전체 통계를 생성합니다.

```bash
python3 scripts/evaluate_chart.py \
  --charts-jsonl data/djmax_4b_charts.jsonl \
  --output data/djmax_4b_eval_summary.json \
  --format json
```

## 웹 서비스

FastAPI, SQLAlchemy, SQLite 기반의 로컬 웹앱입니다. 사용자가 YouTube 링크를 넣으면 WAV를 저장하고, WAV를 분석해 BPM을 자동 측정한 뒤 설정값을 바탕으로 4B 채보를 생성합니다. 생성된 채보는 브라우저에서 바로 플레이할 수 있습니다.

### 실행

```bash
.venv/bin/python -m uvicorn web_app.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 접속합니다.

```text
http://127.0.0.1:8000/
```

### 저장 위치

- WAV 파일: `audio/web/`
- SQLite DB: `data/rhythm_web.sqlite`

### DB 테이블

`wav_songs`

- `id`
- `youtube_url`
- `title`
- `wav_path`
- `created_at`

`chart_data`

- `id`
- `song_id`
- `name`
- `password_hash`
- `key_bindings_json`
- `chart_json`
- `difficulty`
- `tap_ratio`
- `hold_ratio`
- `key_count`
- `bpm`
- `tap_threshold`
- `hold_threshold`
- `created_at`

같은 YouTube 링크가 이미 저장되어 있으면 새로 다운로드하지 않고 DB에 저장된 곡과 채보 목록을 먼저 반환합니다. 저장된 채보가 있으면 프론트에서 첫 번째 채보를 바로 플레이할 수 있게 불러옵니다.

새 채보를 만들 때 채보 이름, 관리 비밀번호, 4개 레인의 플레이 키를 설정합니다. 관리 비밀번호는 PBKDF2 해시로 저장되며 원문은 DB에 남지 않습니다. 채보 이름 변경과 삭제에는 생성할 때 입력한 비밀번호가 필요합니다. 마이그레이션 전에 생성된 기존 채보는 관리 비밀번호가 없으므로 이름 변경과 삭제가 잠깁니다.
