import os
from pathlib import Path

import yt_dlp


def download_youtube_as_wav(video_url, output_path="."):
    """
    유튜브 URL을 입력받아 WAV 파일로 추출하는 함수
    """
    print(f"[{video_url}] 다운로드 및 WAV 변환을 시작합니다...")
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    # yt-dlp 옵션 설정
    ydl_opts = {
        'format': 'bestaudio/best',  # 최고 품질의 오디오 선택
        'outtmpl': os.path.join(str(output_dir), '%(title)s.%(ext)s'),  # 저장 파일명 설정
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',  # WAV 형식으로 변환
            'preferredquality': '192',
        }],
        'nocheckcertificate': True,  # <--- [이 줄을 새로 추가해 주세요!]
        'quiet': False  # 진행 상황을 콘솔에 출력
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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


# --- 실행 부분 ---
if __name__ == "__main__":
    # 추출하고 싶은 유튜브 영상의 URL을 아래에 입력하세요.
    url = input("유튜브 영상 URL을 입력하세요: ")

    download_youtube_as_wav(url)
