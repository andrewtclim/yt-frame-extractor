import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
import uuid
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from extract import FFMPEG, YTDLP, download_video, extract_and_dedup
from export import build_pdf

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup checks
# ---------------------------------------------------------------------------

def _check_tools() -> None:
    missing = []
    for name, known_path in [("ffmpeg", FFMPEG), ("yt-dlp", YTDLP)]:
        if not (shutil.which(name) or os.path.isfile(known_path)):
            missing.append(name)
    if missing:
        logger.error("Missing required tools: %s — install them and retry.", missing)
        sys.exit(1)
    logger.info("ffmpeg: %s", FFMPEG)
    logger.info("yt-dlp: %s", YTDLP)

_check_tools()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="YT Frame Extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# frame_id -> {path, timestamp, timestamp_str}
frame_store: dict[str, dict] = {}

# session_id -> {video_path, session_dir, frame_ids}
session_store: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ProcessRequest(BaseModel):
    url: str

class RescanRequest(BaseModel):
    session_id: str
    threshold: float

class ExportRequest(BaseModel):
    frame_ids: list[str]
    stamp_timestamps: bool = True

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_frames(frames: list[dict]) -> list[dict]:
    """Add frames to frame_store; return the response-safe list."""
    response_frames = []
    for f in frames:
        fid = f["id"]
        frame_store[fid] = {
            "path": f["path"],
            "timestamp": f["timestamp"],
            "timestamp_str": f["timestamp_str"],
        }
        response_frames.append({
            "id": fid,
            "timestamp": f["timestamp"],
            "timestamp_str": f["timestamp_str"],
            "thumbnail_url": f"/frames/{fid}",
        })
    return response_frames


def _drop_session_frames(session_id: str) -> None:
    """Delete frame files and frame_store entries for a session."""
    for fid in session_store.get(session_id, {}).get("frame_ids", []):
        info = frame_store.pop(fid, None)
        if info:
            try:
                os.remove(info["path"])
            except OSError:
                pass


def _drop_old_videos() -> None:
    """Remove downloaded video files from all existing sessions.

    Called before starting a new download so at most one video lives on disk.
    """
    for sdata in session_store.values():
        vp = sdata.get("video_path")
        if vp and os.path.exists(vp):
            try:
                os.remove(vp)
            except OSError:
                pass
        sdata["video_path"] = None

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/process")
async def process(req: ProcessRequest):
    url = req.url
    session_id = str(uuid.uuid4())

    async def generate() -> AsyncIterator[str]:
        session_dir = tempfile.mkdtemp(prefix="ytframes_")

        # Keep at most one video on disk at a time
        _drop_old_videos()

        try:
            yield json.dumps({"status": "downloading"}) + "\n"

            video_path = await asyncio.to_thread(download_video, url, session_dir)

            yield json.dumps({"status": "extracting"}) + "\n"

            frames = await asyncio.to_thread(extract_and_dedup, video_path, session_dir)

            response_frames = _register_frames(frames)
            frame_ids = [f["id"] for f in response_frames]

            session_store[session_id] = {
                "video_path": video_path,   # kept for /rescan
                "session_dir": session_dir,
                "frame_ids": frame_ids,
            }

            yield json.dumps({
                "status": "done",
                "session_id": session_id,
                "frames": response_frames,
            }) + "\n"

        except Exception as e:
            logger.exception("Error processing %s", url)
            yield json.dumps({"status": "error", "message": str(e)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/rescan")
async def rescan(req: RescanRequest):
    if req.session_id not in session_store:
        raise HTTPException(404, "Session not found. Process a video first.")

    session = session_store[req.session_id]
    video_path = session.get("video_path")
    session_dir = session.get("session_dir")

    if not video_path or not os.path.exists(video_path):
        raise HTTPException(410, "Video file no longer available. Process the URL again.")

    async def generate() -> AsyncIterator[str]:
        try:
            yield json.dumps({"status": "scanning"}) + "\n"

            # Clean up old frames before re-extracting into the same dir
            _drop_session_frames(req.session_id)

            frames = await asyncio.to_thread(
                extract_and_dedup, video_path, session_dir, req.threshold
            )

            response_frames = _register_frames(frames)
            session_store[req.session_id]["frame_ids"] = [f["id"] for f in response_frames]

            yield json.dumps({"status": "done", "frames": response_frames}) + "\n"

        except Exception as e:
            logger.exception("Error during rescan (session %s)", req.session_id)
            yield json.dumps({"status": "error", "message": str(e)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/frames/{frame_id}")
async def get_frame(frame_id: str):
    if frame_id not in frame_store:
        raise HTTPException(status_code=404, detail="Frame not found")
    path = frame_store[frame_id]["path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=410, detail="Frame file no longer available")
    with open(path, "rb") as f:
        return Response(content=f.read(), media_type="image/jpeg")


@app.post("/export")
async def export(req: ExportRequest):
    frame_ids = list(dict.fromkeys(req.frame_ids))

    missing = [fid for fid in frame_ids if fid not in frame_store]
    if missing:
        raise HTTPException(status_code=404, detail=f"Frames not found: {missing[:5]}")

    frame_infos = [
        {"path": frame_store[fid]["path"], "timestamp_str": frame_store[fid]["timestamp_str"]}
        for fid in frame_ids
    ]

    pdf_bytes = await asyncio.to_thread(build_pdf, frame_infos, req.stamp_timestamps)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="frames.pdf"'},
    )
