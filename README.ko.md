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

주의: YouTube에서 DJMAX 음원을 자동 검색/다운로드하는 도구는 포함하지 않습니다. 저작권과 플랫폼 약관 이슈가 있으므로, 학습에는 직접 권리를 가진 음원 파일이나 허가된 방식으로 준비한 로컬 오디오를 사용하세요.

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
