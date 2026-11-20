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
    return {"status": "online", "message": "HypeCut Render Cloud Export Server is running!"}

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "HypeCut Cloud Server"}

@app.post("/export-clip")
def export_clip(req: ClipRequest):
    output_filename = f"hypecut_{uuid.uuid4().hex[:8]}.mp4"
    input_file = "input_source.mp4"
    
    # Clean up old files if any
    for f in [input_file, output_filename]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass

    try:
        # Ensure yt-dlp is latest to avoid YouTube 403 blocks
        subprocess.run(["pip", "install", "--upgrade", "yt-dlp"], capture_output=True, timeout=30)

        # 1. Download exact clip section using android client bypass
        section_spec = f"*{req.start_seconds}-{req.end_seconds}"
        dl_cmd = [
            "yt-dlp",
            "--extractor-args", "youtube:player_client=android,web",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4] / b",
            "--download-sections", section_spec,
            "-o", input_file,
            req.youtube_url
        ]
        
        result = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0 or not os.path.exists(input_file):
            err_msg = result.stderr[-400:] if result.stderr else "Unknown yt-dlp error"
            raise HTTPException(status_code=400, detail=f"yt-dlp download failed: {err_msg}")

        # 2. Determine video resolution based on aspect ratio
        if req.aspect_ratio == "9:16":
            vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        elif req.aspect_ratio == "4:5":
            vf = "scale=1080:1350:force_original_aspect_ratio=increase,crop=1080:1350"
        elif req.aspect_ratio == "1:1":
            vf = "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
        else: # 16:9
            vf = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"

        # 3. Process video & audio using ffmpeg
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", input_file,
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            output_filename
        ]
        
        ff_result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=120)
        if ff_result.returncode != 0 or not os.path.exists(output_filename):
            err_msg = ff_result.stderr[-300:] if ff_result.stderr else "FFmpeg error"
            raise HTTPException(status_code=500, detail=f"FFmpeg processing failed: {err_msg}")

        return FileResponse(
            output_filename,
            media_type="video/mp4",
            filename="HypeCut_RealHD_Export.mp4"
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
