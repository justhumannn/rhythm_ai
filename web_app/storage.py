from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import httpx


APP_ENV = os.environ.get("RHYTHM_ENV", "local").casefold()
STORAGE_BACKEND = os.environ.get(
    "RHYTHM_STORAGE_BACKEND",
    "local" if APP_ENV == "local" else "supabase",
).casefold()
SUPABASE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "rhythm-audio")
MAX_AUDIO_BYTES = int(os.environ.get("YOUTUBE_MAX_FILESIZE_BYTES", "524288000"))
SUPABASE_MAX_FILE_BYTES = int(
    os.environ.get("SUPABASE_MAX_FILE_BYTES", str(50 * 1024 * 1024))
)
SIGNED_URL_SECONDS = int(os.environ.get("SUPABASE_SIGNED_URL_SECONDS", "3600"))

ROOT = Path(__file__).resolve().parents[1]
LOCAL_STORAGE_DIR = Path(
    os.environ.get("RHYTHM_STORAGE_DIR", ROOT / "audio" / "web")
).expanduser()
LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def store_audio(local_path: str | Path) -> str:
    source = Path(local_path)
    if STORAGE_BACKEND == "local":
        return str(source.resolve())
    if STORAGE_BACKEND != "supabase":
        raise RuntimeError(f"지원하지 않는 저장소 백엔드입니다: {STORAGE_BACKEND}")
    if source.stat().st_size > SUPABASE_MAX_FILE_BYTES:
        limit_mb = SUPABASE_MAX_FILE_BYTES // (1024 * 1024)
        raise RuntimeError(
            f"Supabase 무료 플랜의 파일당 {limit_mb}MB 제한을 초과했습니다."
        )

    ensure_bucket()
    object_path = f"songs/{uuid4().hex}.wav"
    with source.open("rb") as audio:
        storage_bucket().upload(
            path=object_path,
            file=audio,
            file_options={
                "content-type": "audio/wav",
                "cache-control": "3600",
                "upsert": "false",
            },
        )
    return f"supabase://{SUPABASE_BUCKET}/{object_path}"


@contextmanager
def materialize_audio(reference: str):
    remote = parse_supabase_reference(reference)
    if remote is None:
        path = Path(reference)
        if not path.exists():
            raise FileNotFoundError(f"WAV 파일을 찾을 수 없습니다: {path}")
        yield path
        return

    url = create_signed_url(reference)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output:
            temp_path = Path(output.name)
            total = 0
            with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_AUDIO_BYTES:
                        raise RuntimeError("Supabase WAV 파일 크기 제한을 초과했습니다.")
                    output.write(chunk)
        yield temp_path
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def create_signed_url(reference: str) -> str:
    remote = parse_supabase_reference(reference)
    if remote is None:
        raise ValueError("Supabase Storage 참조가 아닙니다.")
    bucket, object_path = remote
    response = supabase_client().storage.from_(bucket).create_signed_url(
        object_path,
        SIGNED_URL_SECONDS,
    )
    signed_url = (
        response.get("signedURL")
        or response.get("signedUrl")
        or response.get("signed_url")
    )
    if not signed_url:
        raise RuntimeError("Supabase signed URL을 생성하지 못했습니다.")
    if signed_url.startswith("/"):
        return f"{supabase_url()}{signed_url}"
    return signed_url


def delete_audio(reference: str) -> None:
    remote = parse_supabase_reference(reference)
    if remote is None:
        Path(reference).unlink(missing_ok=True)
        return
    bucket, object_path = remote
    supabase_client().storage.from_(bucket).remove([object_path])


def parse_supabase_reference(reference: str) -> tuple[str, str] | None:
    prefix = "supabase://"
    if not reference.startswith(prefix):
        return None
    bucket, separator, object_path = reference[len(prefix):].partition("/")
    if not separator or not bucket or not object_path:
        raise ValueError("올바르지 않은 Supabase Storage 참조입니다.")
    return bucket, object_path


def storage_status() -> dict:
    status = {"backend": STORAGE_BACKEND}
    if STORAGE_BACKEND == "local":
        status["path"] = str(LOCAL_STORAGE_DIR)
    else:
        status["bucket"] = SUPABASE_BUCKET
        status["configured"] = bool(
            os.environ.get("SUPABASE_URL")
            and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        )
    return status


@lru_cache(maxsize=1)
def supabase_client():
    try:
        from supabase import create_client
    except ImportError as exc:
        raise RuntimeError("supabase 패키지가 설치되지 않았습니다.") from exc
    return create_client(supabase_url(), supabase_service_role_key())


def supabase_url() -> str:
    value = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not value:
        raise RuntimeError("SUPABASE_URL이 필요합니다.")
    return value


def supabase_service_role_key() -> str:
    value = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not value:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY가 필요합니다.")
    return value


def storage_bucket():
    return supabase_client().storage.from_(SUPABASE_BUCKET)


@lru_cache(maxsize=1)
def ensure_bucket() -> None:
    client = supabase_client()
    bucket_names = set()
    for bucket in client.storage.list_buckets():
        if hasattr(bucket, "name"):
            bucket_names.add(bucket.name)
        elif isinstance(bucket, dict):
            bucket_names.add(bucket.get("name") or bucket.get("id"))
    if SUPABASE_BUCKET not in bucket_names:
        client.storage.create_bucket(
            SUPABASE_BUCKET,
            options={
                "public": False,
                "file_size_limit": SUPABASE_MAX_FILE_BYTES,
                "allowed_mime_types": ["audio/wav", "audio/x-wav"],
            },
        )
