from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException


MODEL_SERVICE_URL = os.environ.get("AI_SERVICE_URL", "").rstrip("/")
MODEL_SERVICE_TOKEN = os.environ.get("AI_SERVICE_TOKEN", "")
MODEL_SERVICE_TIMEOUT = float(os.environ.get("AI_SERVICE_TIMEOUT_SECONDS", "600"))


def model_service_enabled() -> bool:
    return bool(MODEL_SERVICE_URL)


def generate_chart_remotely(
    *,
    audio_path: str | Path,
    title: str,
    bpm: float | None,
    difficulty: str,
    tap_ratio: float,
    hold_ratio: float,
    key_count: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not MODEL_SERVICE_URL:
        raise RuntimeError("AI_SERVICE_URL이 설정되지 않았습니다.")

    headers = {}
    if MODEL_SERVICE_TOKEN:
        headers["Authorization"] = f"Bearer {MODEL_SERVICE_TOKEN}"

    data: dict[str, str] = {
        "title": title,
        "difficulty": difficulty,
        "tap_ratio": str(tap_ratio),
        "hold_ratio": str(hold_ratio),
        "key_count": str(key_count),
    }
    if bpm is not None:
        data["bpm"] = str(bpm)

    try:
        with Path(audio_path).open("rb") as audio:
            files = {"audio": (Path(audio_path).name, audio, "audio/wav")}
            response = httpx.post(
                f"{MODEL_SERVICE_URL}/generate",
                data=data,
                files=files,
                headers=headers,
                timeout=MODEL_SERVICE_TIMEOUT,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"모델 서버 연결 실패: {exc}",
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"모델 서버 오류: {read_error_detail(response)}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="모델 서버가 올바른 JSON을 반환하지 않았습니다.",
        ) from exc

    chart = payload.get("chart")
    thresholds = payload.get("thresholds")
    bpm_analysis = payload.get("bpm_analysis")
    if not isinstance(chart, dict) or not isinstance(thresholds, dict):
        raise HTTPException(
            status_code=502,
            detail="모델 서버 응답에 chart 또는 thresholds가 없습니다.",
        )
    if not isinstance(bpm_analysis, dict):
        bpm_analysis = chart.get("generator", {}).get("bpmAnalysis", {})
    return chart, thresholds, bpm_analysis


def analyze_bpm_remotely(
    *,
    audio_path: str | Path,
    title: str | None = None,
) -> dict[str, Any]:
    if not MODEL_SERVICE_URL:
        raise RuntimeError("AI_SERVICE_URL이 설정되지 않았습니다.")

    headers = {}
    if MODEL_SERVICE_TOKEN:
        headers["Authorization"] = f"Bearer {MODEL_SERVICE_TOKEN}"
    data = {}
    if title:
        data["title"] = title

    try:
        with Path(audio_path).open("rb") as audio:
            files = {"audio": (Path(audio_path).name, audio, "audio/wav")}
            response = httpx.post(
                f"{MODEL_SERVICE_URL}/bpm",
                data=data,
                files=files,
                headers=headers,
                timeout=MODEL_SERVICE_TIMEOUT,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"모델 서버 BPM 분석 연결 실패: {exc}",
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"모델 서버 BPM 분석 오류: {read_error_detail(response)}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="모델 서버가 올바른 BPM JSON을 반환하지 않았습니다.",
        ) from exc
    bpm_analysis = payload.get("bpm_analysis")
    if not isinstance(bpm_analysis, dict):
        raise HTTPException(
            status_code=502,
            detail="모델 서버 응답에 bpm_analysis가 없습니다.",
        )
    return bpm_analysis


def read_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500] or f"HTTP {response.status_code}"
    detail = body.get("detail") if isinstance(body, dict) else None
    return str(detail or body or f"HTTP {response.status_code}")
