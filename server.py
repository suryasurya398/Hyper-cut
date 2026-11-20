from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess
import os
import uuid

app = FastAPI()

class CaptionItem(BaseModel):
    offset_seconds: int = 0
    duration_seconds: int = 3
    text: str = ""

class ClipRequest(BaseModel):
    youtube_url: str
    start_seconds: int = 0
    end_seconds: int = 30
    aspect_ratio: str = "9:16"
    hook_text: str = ""
    captions: list[CaptionItem] = []

@app.get("/")
def home():
    return {"status": "online", "message": "HypeCut Cloud Server Active"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/export-clip")
def export_clip(req: ClipRequest):
    output_filename = f"hypecut_{uuid.uuid4().hex[:8]}.mp4"
    input_file = "input_source.mp4"
    
    for f in [input_file, output_filename]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass

    try:
        # Download using yt-dlp with multiple client emulations to bypass 403
        section_spec = f"*{req.start_seconds}-{req.end_seconds}"
        dl_cmd = [
            "yt-dlp",
            "--no-check-certificates",
            "--geo-bypass",
            "--extractor-args", "youtube:player_client=ios,web",
            "--user-agent", "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            "-f", "best[ext=mp4]/best",
            "--download-sections", section_spec,
            "-o", input_file,
            req.youtube_url
        ]
        
        res = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=180)
        if res.returncode != 0 or not os.path.exists(input_file):
            # Fallback to generic downloader format
            dl_cmd_fallback = [
                "yt-dlp",
                "--no-check-certificates",
                "-f", "b",
                "--download-sections", section_spec,
                "-o", input_file,
                req.youtube_url
            ]
            res_fb = subprocess.run(dl_cmd_fallback, capture_output=True, text=True, timeout=120)
            if res_fb.returncode != 0 or not os.path.exists(input_file):
                err = res.stderr[-250:] if res.stderr else "Download blocked by YouTube 403"
                raise HTTPException(status_code=400, detail=f"Download failed: {err}")

        # Aspect Ratio Video Scaling
        if req.aspect_ratio == "9:16":
            vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        elif req.aspect_ratio == "4:5":
            vf = "scale=1080:1350:force_original_aspect_ratio=increase,crop=1080:1350"
        elif req.aspect_ratio == "1:1":
            vf = "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
        else:
            vf = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"

        # FFmpeg render
        ff_cmd = [
            "ffmpeg", "-y",
            "-i", input_file,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_filename
        ]
        
        ff_res = subprocess.run(ff_cmd, capture_output=True, text=True, timeout=120)
        if ff_res.returncode != 0 or not os.path.exists(output_filename):
            raise HTTPException(status_code=500, detail="FFmpeg render failed")

        return FileResponse(output_filename, media_type="video/mp4", filename="HypeCut_Export.mp4")

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
