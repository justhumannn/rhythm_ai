import os
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp


ALLOWED_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


def download_youtube_as_wav(video_url, output_path="."):
    """
    유튜브 URL을 입력받아 WAV 파일로 추출하는 함수
    """
    print(f"[{video_url}] 다운로드 및 WAV 변환을 시작합니다...")
    validate_youtube_url(video_url)
    output_dir = Path(output_path).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    max_duration = int(os.environ.get("YOUTUBE_MAX_DURATION_SECONDS", "600"))
    max_filesize = int(os.environ.get("YOUTUBE_MAX_FILESIZE_BYTES", "524288000"))

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(str(output_dir), "%(id)s.%(ext)s"),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        "noplaylist": True,
        "max_filesize": max_filesize,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            duration = int(info.get("duration") or 0)
            if duration <= 0:
                raise ValueError("영상 길이를 확인할 수 없습니다.")
            if duration > max_duration:
                raise ValueError(
                    f"영상은 최대 {max_duration // 60}분까지 지원합니다."
                )
            info = ydl.extract_info(video_url, download=True)
            downloaded_path = Path(ydl.prepare_filename(info)).with_suffix(".wav")
        print("성공적으로 다운로드 및 변환이 완료되었습니다!")
        return {
            "title": info.get("title") or downloaded_path.stem,
            "path": str(downloaded_path),
            "youtube_url": video_url,
        }
    except Exception as e:
        print(f"에러가 발생했습니다: {e}")
        print("FFmpeg가 시스템에 제대로 설치되어 있는지 확인해 주세요.")
        raise


def validate_youtube_url(video_url: str) -> None:
    parsed = urlparse(video_url)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or hostname not in ALLOWED_YOUTUBE_HOSTS:
        raise ValueError("YouTube 또는 youtu.be 링크만 사용할 수 있습니다.")


# --- 실행 부분 ---
if __name__ == "__main__":
    # 추출하고 싶은 유튜브 영상의 URL을 아래에 입력하세요.
    url = input("유튜브 영상 URL을 입력하세요: ")

    download_youtube_as_wav(url)
