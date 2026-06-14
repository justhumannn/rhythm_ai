from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from web_app.bpm import analyze_bpm
from web_app.chart_generator import chart_from_json, chart_to_json, generate_chart
from web_app.database import Base, SessionLocal, engine
from web_app.migrations import migrate_database
from web_app.models import Chart, Song
from web_app.security import hash_password, verify_password
from youtube_to_wav import download_youtube_as_wav


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "web_app" / "static"
configured_storage = os.environ.get("RHYTHM_STORAGE_DIR")
if configured_storage:
    STORAGE_DIR = Path(configured_storage).expanduser()
    UPLOAD_DIR = STORAGE_DIR / "audio"
else:
    STORAGE_DIR = ROOT / "audio" / "web"
    UPLOAD_DIR = STORAGE_DIR
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
HEAVY_JOB_SLOTS = threading.BoundedSemaphore(
    int(os.environ.get("RHYTHM_MAX_CONCURRENT_JOBS", "1"))
)

Base.metadata.create_all(bind=engine)
migrate_database(engine)

app = FastAPI(title="Rhythm AI Web")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class SongRequest(BaseModel):
    youtube_url: str = Field(min_length=5)


class GenerateRequest(BaseModel):
    song_id: int
    chart_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=4, max_length=128)
    difficulty: str = "hard"
    tap_ratio: float = Field(default=55, ge=0, le=100)
    hold_ratio: float = Field(default=60, ge=0, le=100)
    key_count: int = Field(default=4, ge=4, le=8)
    key_bindings: list[str]


class ChartManageRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class ChartRenameRequest(ChartManageRequest):
    name: str = Field(min_length=1, max_length=160)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def healthcheck(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    checkpoint = os.environ.get(
        "RHYTHM_CHECKPOINT",
        ROOT / "checkpoints" / "djmax_4b_aligned.pt",
    )
    return {
        "status": "ok",
        "database": "ok",
        "checkpoint": Path(checkpoint).exists(),
        "storage": str(STORAGE_DIR),
    }


@app.post("/api/songs")
def create_or_get_song(payload: SongRequest, db: Session = Depends(get_db)):
    song = db.query(Song).filter(Song.youtube_url == payload.youtube_url).first()
    if song is None:
        try:
            with heavy_job_slot():
                result = download_youtube_as_wav(
                    payload.youtube_url,
                    output_path=UPLOAD_DIR,
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"다운로드 실패: {exc}") from exc
        song = Song(
            youtube_url=payload.youtube_url,
            title=result["title"],
            wav_path=result["path"],
        )
        db.add(song)
        db.commit()
        db.refresh(song)

    return song_payload(song)


@app.get("/api/songs/{song_id}")
def get_song(song_id: int, db: Session = Depends(get_db)):
    song = db.get(Song, song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="노래를 찾을 수 없습니다.")
    return song_payload(song)


@app.post("/api/charts")
def create_chart(payload: GenerateRequest, db: Session = Depends(get_db)):
    song = db.get(Song, payload.song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="노래를 찾을 수 없습니다.")
    if not Path(song.wav_path).exists():
        raise HTTPException(status_code=404, detail="WAV 파일을 찾을 수 없습니다.")
    key_bindings = validate_key_bindings(payload.key_bindings, payload.key_count)

    try:
        with heavy_job_slot():
            bpm_analysis = analyze_bpm(song.wav_path, title=song.title)
            bpm = bpm_analysis.bpm
            chart_data, thresholds = generate_chart(
                audio_path=song.wav_path,
                title=song.title,
                bpm=bpm,
                difficulty=payload.difficulty,
                tap_ratio=payload.tap_ratio,
                hold_ratio=payload.hold_ratio,
                key_count=payload.key_count,
            )
            chart_data["generator"]["bpmAnalysis"] = bpm_analysis.to_dict()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"채보 생성 실패: {exc}") from exc

    chart = Chart(
        song_id=song.id,
        name=payload.chart_name.strip(),
        password_hash=hash_password(payload.password),
        key_bindings_json=json.dumps(key_bindings),
        chart_json=chart_to_json(chart_data),
        difficulty=payload.difficulty,
        tap_ratio=payload.tap_ratio,
        hold_ratio=payload.hold_ratio,
        key_count=payload.key_count,
        bpm=bpm,
        tap_threshold=thresholds["tap_threshold"],
        hold_threshold=thresholds["hold_threshold"],
    )
    db.add(chart)
    db.commit()
    db.refresh(chart)
    return chart_payload(chart)


@app.get("/api/charts/{chart_id}")
def get_chart(chart_id: int, db: Session = Depends(get_db)):
    chart = db.get(Chart, chart_id)
    if chart is None:
        raise HTTPException(status_code=404, detail="채보를 찾을 수 없습니다.")
    return chart_payload(chart)


@app.delete("/api/charts/{chart_id}")
def delete_chart(
    chart_id: int,
    payload: ChartManageRequest,
    db: Session = Depends(get_db),
):
    chart = db.get(Chart, chart_id)
    if chart is None:
        raise HTTPException(status_code=404, detail="채보를 찾을 수 없습니다.")
    require_chart_password(chart, payload.password)

    song_id = chart.song_id
    db.delete(chart)
    db.commit()
    return {"deleted": True, "chart_id": chart_id, "song_id": song_id}


@app.patch("/api/charts/{chart_id}")
def rename_chart(
    chart_id: int,
    payload: ChartRenameRequest,
    db: Session = Depends(get_db),
):
    chart = db.get(Chart, chart_id)
    if chart is None:
        raise HTTPException(status_code=404, detail="채보를 찾을 수 없습니다.")
    require_chart_password(chart, payload.password)

    chart.name = payload.name.strip()
    db.commit()
    db.refresh(chart)
    return chart_payload(chart)


@app.get("/api/songs/{song_id}/audio")
def get_audio(song_id: int, db: Session = Depends(get_db)):
    song = db.get(Song, song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="노래를 찾을 수 없습니다.")
    path = Path(song.wav_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="WAV 파일을 찾을 수 없습니다.")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


def song_payload(song: Song) -> dict:
    return {
        "id": song.id,
        "youtube_url": song.youtube_url,
        "title": song.title,
        "charts": [chart_summary(chart) for chart in song.charts],
    }


def chart_summary(chart: Chart) -> dict:
    data = chart_from_json(chart.chart_json, hold_ratio=chart.hold_ratio)
    bpm_analysis = data.get("generator", {}).get("bpmAnalysis", {})
    return {
        "id": chart.id,
        "song_id": chart.song_id,
        "name": chart.name or f"{chart.difficulty} #{chart.id}",
        "manageable": bool(chart.password_hash),
        "difficulty": chart.difficulty,
        "tap_ratio": chart.tap_ratio,
        "hold_ratio": chart.hold_ratio,
        "key_count": chart.key_count,
        "key_bindings": load_key_bindings(chart),
        "bpm": chart.bpm,
        "bpm_confidence": bpm_analysis.get("confidence"),
        "bpm_source": bpm_analysis.get("source"),
        "bpm_ambiguous": bpm_analysis.get("ambiguous"),
        "note_count": data.get("noteCount", 0),
        "created_at": chart.created_at.isoformat(),
    }


def chart_payload(chart: Chart) -> dict:
    payload = chart_summary(chart)
    payload["chart"] = chart_from_json(chart.chart_json, hold_ratio=chart.hold_ratio)
    return payload


def validate_key_bindings(bindings: list[str], key_count: int) -> list[str]:
    if key_count != 4:
        raise HTTPException(status_code=400, detail="현재 AI 모델은 4B만 지원합니다.")
    if len(bindings) != key_count:
        raise HTTPException(status_code=400, detail="4개 레인의 키를 모두 설정해 주세요.")
    cleaned = [binding.strip() for binding in bindings]
    if any(not binding or len(binding) > 40 for binding in cleaned):
        raise HTTPException(status_code=400, detail="올바른 키 설정이 아닙니다.")
    if len(set(cleaned)) != len(cleaned):
        raise HTTPException(status_code=400, detail="각 레인은 서로 다른 키를 사용해야 합니다.")
    return cleaned


@contextmanager
def heavy_job_slot():
    if not HEAVY_JOB_SLOTS.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="다른 음원 작업이 진행 중입니다. 잠시 후 다시 시도해 주세요.",
        )
    try:
        yield
    finally:
        HEAVY_JOB_SLOTS.release()


def load_key_bindings(chart: Chart) -> list[str]:
    try:
        bindings = json.loads(chart.key_bindings_json)
    except (TypeError, json.JSONDecodeError):
        bindings = []
    if not isinstance(bindings, list) or len(bindings) != 4:
        return ["KeyD", "KeyF", "KeyJ", "KeyK"]
    return [str(binding) for binding in bindings]


def require_chart_password(chart: Chart, password: str) -> None:
    if not chart.password_hash:
        raise HTTPException(
            status_code=403,
            detail="기존 채보에는 관리 비밀번호가 없어 변경하거나 삭제할 수 없습니다.",
        )
    if not verify_password(password, chart.password_hash):
        raise HTTPException(status_code=403, detail="비밀번호가 올바르지 않습니다.")
