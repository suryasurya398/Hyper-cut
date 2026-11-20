import os
import subprocess
import tempfile
import uuid
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="HypeCut Cloud Clip Server")


class CaptionItem(BaseModel):
    offsetSeconds: int
    durationSeconds: int
    text: str


class ExportRequest(BaseModel):
    youtube_url: str
    start_sec: int
    end_sec: int
    aspect_ratio: str = "9:16"
    fps: int = 30
    high_quality_1080p: bool = True
    top_overlay: str = ""
    captions: List[CaptionItem] = []


def fmt_srt(sec: int) -> str:
    sec = max(0, sec)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d},000"


def fmt_section(sec: int) -> str:
    sec = max(0, sec)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


@app.get("/health")
def health():
    return {"status": "ok", "engine": "yt-dlp + ffmpeg"}


@app.post("/export-clip")
def export_clip(req: ExportRequest):
    job_id = str(uuid.uuid4())[:8]
    work_dir = tempfile.mkdtemp(prefix=f"hypecut_{job_id}_")
    raw_mp4 = os.path.join(work_dir, "raw.mp4")
    srt_path = os.path.join(work_dir, "captions.srt")
    out_mp4 = os.path.join(work_dir, f"hypecut_{job_id}.mp4")

    start_s = max(0, req.start_sec)
    end_s = max(start_s + 5, req.end_sec)
    section = f"*{fmt_section(start_s)}-{fmt_section(end_s)}"

    # 1. Download ONLY the requested clip section with real HD video + original audio
    yt_cmd = [
        "yt-dlp",
        "--download-sections", section,
        "--force-keyframes-at-cuts",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", raw_mp4,
        req.youtube_url,
    ]
    yt_res = subprocess.run(yt_cmd, capture_output=True, text=True, timeout=180)
    if yt_res.returncode != 0 or not os.path.exists(raw_mp4):
        raise HTTPException(
            status_code=500,
            detail=f"yt-dlp failed: {(yt_res.stderr or yt_res.stdout)[-300:]}"
        )

    # 2. Build SRT subtitles file if captions are provided
    has_srt = False
    if req.captions:
        with open(srt_path, "w", encoding="utf-8") as f:
            for idx, c in enumerate(req.captions, start=1):
                st = fmt_srt(c.offsetSeconds)
                en = fmt_srt(c.offsetSeconds + max(2, c.durationSeconds))
                f.write(f"{idx}\n{st} --> {en}\n{c.text}\n\n")
        has_srt = True

    # 3. Aspect ratio crop + scale filter
    target_h = 1920 if req.high_quality_1080p else 1280
    if req.aspect_ratio == "9:16":
        w, h = (1080, 1920) if req.high_quality_1080p else (720, 1280)
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    elif req.aspect_ratio == "4:5":
        w, h = (1080, 1350) if req.high_quality_1080p else (720, 900)
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    elif req.aspect_ratio == "1:1":
        w = 1080 if req.high_quality_1080p else 720
        vf = f"scale={w}:{w}:force_original_aspect_ratio=increase,crop={w}:{w}"
    else:
        w, h = (1920, 1080) if req.high_quality_1080p else (1280, 720)
        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"

    if has_srt:
        escaped_srt = srt_path.replace("\\", "/").replace(":", "\\:")
        vf += f",subtitles='{escaped_srt}':force_style='FontName=DejaVu Sans,FontSize=18,PrimaryColour=&H0000B8FF,OutlineColour=&H00000000,BorderStyle=3,Outline=2,Alignment=2,MarginV=45'"

    # 4. Render final MP4 with original AAC audio + chosen FPS
    ff_cmd = [
        "ffmpeg", "-y",
        "-i", raw_mp4,
        "-vf", vf,
        "-r", str(max(24, min(60, req.fps))),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        out_mp4,
    ]
    ff_res = subprocess.run(ff_cmd, capture_output=True, text=True, timeout=240)
    if ff_res.returncode != 0 or not os.path.exists(out_mp4):
        raise HTTPException(
            status_code=500,
            detail=f"ffmpeg failed: {(ff_res.stderr or ff_res.stdout)[-300:]}"
        )

    return FileResponse(
        out_mp4,
        media_type="video/mp4",
        filename=f"HypeCut_{job_id}.mp4",
    )
