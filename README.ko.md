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

## 처음 실행: Minimal local demo

외부 음원이나 DJMAX 음원 없이 실제 파이프라인 전체를 확인하는 작은 예제입니다. 준비 스크립트가 저작권 문제가 없는 합성 WAV와 대응하는 4B 채보를 생성합니다.

### 1. 데모 입력 생성

```bash
python3 scripts/prepare_minimal_demo.py
```

생성 파일:

- `demo/audio/Minimal Demo Pulse.wav`
- `demo/data/minimal_charts.jsonl`

### 2. 오디오 매니페스트 생성

```bash
python3 scripts/create_audio_manifest.py \
  --charts demo/data/minimal_charts.jsonl \
  --audio-dir demo/audio \
  --output demo/data/audio_manifest.json \
  --missing-output demo/data/missing_audio_queries.txt
```

정상 실행되면 `matched: 1`, `missing: 0`이 출력됩니다.

### 3. 작은 모델 학습

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

일반 학습보다 작은 모델과 데이터 수를 사용하므로 로컬 환경에서 파이프라인이 작동하는지 빠르게 확인할 수 있습니다.

### 4. 채보 생성

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

### 5. 생성 결과 평가

```bash
python3 scripts/evaluate_chart.py \
  --chart demo/generated/minimal_demo_4b.json \
  --reference-jsonl demo/data/minimal_charts.jsonl \
  --reference-title "Minimal Demo Pulse" \
  --reference-difficulty NM
```

전체 산출물 구조:

```text
demo/
├── audio/Minimal Demo Pulse.wav
├── data/minimal_charts.jsonl
├── data/audio_manifest.json
├── checkpoints/minimal_demo.pt
└── generated/minimal_demo_4b.json
```

이 데모의 2 epoch 모델은 채보 품질을 평가하기 위한 모델이 아니라 설치 상태와 전체 실행 흐름을 검증하기 위한 smoke test입니다.

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

유튜브 영상에서 추출한 음원은 영상마다 음악 시작 시점이 다를 수 있습니다. 학습 전에 오디오 onset과 채보를 비교해 곡별 시간 오프셋을 계산합니다. 이 과정에서 4B 학습에 맞지 않는 5B/6B/8B 게임플레이 음원과 BPM 변화 구간 정보가 없는 곡도 제외합니다.

```bash
.venv/bin/python -B scripts/align_audio_manifest.py \
  --charts data/djmax_4b_charts.jsonl \
  --manifest data/audio_manifest.json \
  --output data/audio_manifest_aligned.json
```

정렬된 manifest에는 `audio_offset_seconds`, `alignment_score`, `training_eligible`, `training_exclusion_reasons`가 추가됩니다.

기존 모델의 공통 가중치를 초기값으로 가져오되, 시간 정렬 라벨이 달라졌으므로 새 체크포인트로 학습합니다.

```bash
.venv/bin/python -B scripts/train_chart_model.py \
  --charts data/djmax_4b_charts.jsonl \
  --audio-manifest data/audio_manifest_aligned.json \
  --output checkpoints/djmax_4b_aligned.pt \
  --init-from checkpoints/djmax_4b_conditional.pt \
  --require-training-eligible \
  --exclude-gameplay-audio \
  --learning-rate 5e-5 \
  --tap-pos-weight 3 \
  --hold-pos-weight 3 \
  --metric-tap-threshold 0.5 \
  --epochs 40
```

이 모델을 이어서 학습할 때는 같은 정렬 manifest와 `--resume`을 사용합니다.

```bash
.venv/bin/python -B scripts/train_chart_model.py \
  --charts data/djmax_4b_charts.jsonl \
  --audio-manifest data/audio_manifest_aligned.json \
  --output checkpoints/djmax_4b_aligned.pt \
  --require-training-eligible \
  --exclude-gameplay-audio \
  --learning-rate 5e-5 \
  --tap-pos-weight 3 \
  --hold-pos-weight 3 \
  --metric-tap-threshold 0.5 \
  --epochs 80 \
  --resume
```

`--exclude-gameplay-audio`는 파일명에서 키 모드가 확인되는 게임플레이 영상 음원을 제외합니다. 게임 키음이 섞인 입력은 정답 노드 정보를 미리 포함하거나 다른 난이도의 키음과 충돌하므로, 새 곡의 순수 음원으로 일반화할 모델에는 사용하지 않는 것이 좋습니다.

정렬 후 loss는 이전 모델과 라벨 정의가 달라 직접 비교할 수 없습니다. `tap_f1`, `hold_f1`, precision, recall도 함께 확인해야 합니다. 탭 로그에는 `0.40~0.70` 범위에서 가장 높은 F1과 임계값이 `tap_best_f1=...@...` 형식으로 출력됩니다.

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
  --reference-difficulty SC \
  --timing-tolerance-beats 0.125
```

레퍼런스를 지정하면 노트 수와 밀도뿐 아니라 같은 lane의 노드가 허용 박자 오차 안에서 일치하는지 `timingMatch` precision/recall/F1도 출력합니다. 생성 품질을 판단할 때는 전체 노트 수보다 `timingMatch.tap.f1`을 우선 확인합니다.

원본 데이터셋 전체 통계를 생성합니다.

```bash
python3 scripts/evaluate_chart.py \
  --charts-jsonl data/djmax_4b_charts.jsonl \
  --output data/djmax_4b_eval_summary.json \
  --format json
```

## 웹 서비스

FastAPI, SQLAlchemy, SQLite 기반의 로컬 웹앱입니다. 사용자가 YouTube 링크를 넣으면 WAV를 저장하고, WAV를 분석해 BPM을 자동 측정한 뒤 설정값을 바탕으로 4B 채보를 생성합니다. 생성된 채보는 브라우저에서 바로 플레이할 수 있습니다.

### BPM 분석

BPM 분석은 전체 음원과 20초 단위 여러 구간을 함께 검사합니다. DJMAX 데이터에 등록된 곡은 유튜브 제목과 오디오 후보를 교차 확인해 공식 BPM을 사용하며, 그 외 곡은 분석 BPM과 신뢰도, 반박/두배박 후보를 저장합니다. 웹 화면에는 BPM 신뢰도와 배수박 모호성 여부가 표시됩니다.

WAV 파일만 따로 분석하려면:

```bash
.venv/bin/python -B scripts/analyze_bpm.py \
  --audio "audio/example.wav" \
  --title "곡 제목"
```

출력의 `source`가 `djmax_catalog`이면 DJMAX 채보 데이터와 오디오 분석이 함께 사용된 값이며, `audio_analysis`이면 오디오만으로 측정한 값입니다. `ambiguous`가 `true`이면 표시 BPM의 절반 또는 두 배도 강한 후보라는 뜻입니다.

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

## 클라우드 배포

초기 공개 배포는 Render의 Docker Web Service, Supabase PostgreSQL, Supabase Storage 조합을 기준으로 구성되어 있습니다.

- `Dockerfile`: Python 3.12, CPU용 PyTorch, ffmpeg를 설치합니다.
- `render.yaml`: 웹 서비스를 생성하고 Supabase DB와 Storage 접속 정보를 secret으로 받습니다.
- 로컬에서는 `RHYTHM_ENV=local`과 `DATABASE_URL`로 SQLite를 SQLAlchemy에서 사용합니다.
- 외부 배포에서는 `RHYTHM_ENV=production`과 `SUPABASE_DATABASE_URL`로 Supabase PostgreSQL을 SQLAlchemy에서 사용합니다.
- 로컬에서는 `RHYTHM_STORAGE_BACKEND=local`로 WAV를 `RHYTHM_STORAGE_DIR`에 저장합니다.
- 운영에서는 `RHYTHM_STORAGE_BACKEND=supabase`로 private Storage bucket에 WAV를 저장합니다.
- `/healthz`: DB 연결, 체크포인트, 저장 경로 상태를 확인합니다.

Render에서 배포하는 순서:

1. Supabase 프로젝트를 만들고 Dashboard의 **Connect**에서 Session Pooler 연결 문자열을 준비합니다.
2. Supabase **Project Settings > API**에서 Project URL과 service role key를 준비합니다. service role key는 브라우저나 GitHub에 노출하면 안 됩니다.
3. 변경 사항과 최신 모델인 `checkpoints/djmax_4b_aligned.pt`를 `justhumannn/rhythm_ai` 저장소에 push합니다.
4. Render Dashboard에서 **New > Blueprint**를 선택합니다.
5. GitHub의 `justhumannn/rhythm_ai` 저장소를 연결합니다.
6. 저장소 루트의 `render.yaml`을 적용합니다.
7. `SUPABASE_DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`를 입력합니다. DB 비밀번호에 특수문자가 있으면 URL 인코딩하고 연결 문자열 끝에 `?sslmode=require`를 붙입니다.
8. 배포가 끝나면 `https://서비스주소/healthz`에서 `status: ok`, `checkpoint: true`, `storage.backend: supabase`를 확인합니다.

현재 Blueprint는 싱가포르 리전과 `standard` 웹 서비스를 사용합니다. Persistent Disk는 필요하지 않습니다. Supabase 무료 플랜의 Storage 용량은 1GB이고 파일 하나의 최대 크기는 50MB입니다. 앱도 업로드 전에 같은 제한을 검사합니다. 무료 할당량을 넘기면 파일을 정리해야 하며, 이 프로젝트는 유료 초과 사용을 전제로 하지 않습니다.

로컬에서 배포 이미지를 확인하려면:

```bash
docker build -t rhythm-ai:local .
docker run --rm -p 8000:8000 \
  -e RHYTHM_STORAGE_BACKEND=local \
  -e RHYTHM_STORAGE_DIR=/app/audio/web \
  rhythm-ai:local
```

환경변수 예시는 `.env.example`에 있습니다. 공개 서비스 보호를 위해 YouTube 링크만 허용하고, 기본 영상 길이는 10분, 파일 크기는 500MB로 제한하며, 다운로드와 AI 생성 작업은 동시에 하나만 실행합니다.

주의사항:

- Supabase bucket은 처음 음원을 저장할 때 private `rhythm-audio` bucket으로 자동 생성됩니다.
- DB에는 실제 로컬 경로 대신 `supabase://rhythm-audio/...` 형식의 객체 참조가 저장됩니다.
- 플레이할 때는 1시간짜리 signed URL을 발급하고, AI 생성 시에는 임시 파일로 내려받은 뒤 즉시 삭제합니다.
- 기존 Persistent Disk나 로컬 `audio/web` 파일은 자동 이전되지 않습니다. 기존 DB의 로컬 파일 경로도 별도 마이그레이션이 필요합니다.
- 클라우드 사업자 IP에서 YouTube 다운로드가 차단될 수 있습니다. 이 경우 사용자가 직접 음원을 업로드하거나 별도의 다운로드 worker를 두는 방식이 필요합니다.
