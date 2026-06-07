import os
import re
import uuid
import shutil
import subprocess
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image
import imagehash

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunable constants — adjust here without hunting through the code
# ---------------------------------------------------------------------------
# SCENE_THRESHOLD: scdet threshold (0–100 scale).
# Lower = more sensitive (more frames); higher = fewer frames.
# Score ranges vary widely by codec and bitrate:
#   AV1 / low-bitrate VP9 (common on YouTube): scores cap at ~5–10 → use 2–4
#   h264 / h265 at typical quality: scores can reach 20–50 → use 10–20
# Default 3.0 works for AV1-encoded educational videos.
# If you get too few frames try 2.0; too many try 5.0.
SCENE_THRESHOLD = 3.0
DEDUP_HASH_THRESHOLD = 5    # max Hamming distance to treat two frames as duplicates
DOWNLOAD_RESOLUTION = 720   # max download height in pixels
# ---------------------------------------------------------------------------

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/anaconda3/envs/ytframes/bin/ffmpeg"
YTDLP = shutil.which("yt-dlp") or "/opt/homebrew/anaconda3/envs/ytframes/bin/yt-dlp"

# Matches scdet stderr log lines:
#   [Parsed_scdet_1 @ 0x...] lavfi.scd.score: 15.625, lavfi.scd.time: 45.2
_SCDET_RE = re.compile(r"lavfi\.scd\.score:\s*([0-9.]+),\s*lavfi\.scd\.time:\s*([0-9.]+)")


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def download_video(url: str, session_dir: str) -> str:
    """Download video with yt-dlp capped at DOWNLOAD_RESOLUTION. Returns path to video file."""
    import yt_dlp

    outtmpl = os.path.join(session_dir, "video.%(ext)s")
    ydl_opts = {
        "format": (
            f"bestvideo[height<={DOWNLOAD_RESOLUTION}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={DOWNLOAD_RESOLUTION}]+bestaudio"
            f"/best[height<={DOWNLOAD_RESOLUTION}]"
        ),
        "outtmpl": outtmpl,
        "ffmpeg_location": os.path.dirname(FFMPEG),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    for candidate in [
        os.path.join(session_dir, "video.mp4"),
        os.path.join(session_dir, f"video.{info.get('ext', 'webm')}"),
    ]:
        if os.path.exists(candidate):
            logger.info("Downloaded: %s", candidate)
            return candidate

    raise FileNotFoundError(f"Download finished but video file not found in {session_dir}")


def _parse_scdet(stderr: str) -> list[float]:
    """Extract scene-change timestamps from scdet stderr log, in chronological order."""
    timestamps = []
    for line in stderr.splitlines():
        m = _SCDET_RE.search(line)
        if m:
            timestamps.append(float(m.group(2)))
    timestamps.sort()
    return timestamps


def extract_frames(video_path: str, session_dir: str, threshold: float | None = None) -> list[dict]:
    """
    Two-pass extraction using the scdet filter (works in ffmpeg 8.x).

    Pass 1: run scdet → null.  scdet logs each detected scene change to stderr
            as "lavfi.scd.time: T" — no encoder or JPEG output needed.
    Pass 2: for each timestamp, extract one frame with a two-seek strategy
            (fast input-seek to T-3s, then short output-seek for frame accuracy).
    """
    # --- Pass 1: scene detection ---
    t = threshold if threshold is not None else SCENE_THRESHOLD
    detect_cmd = [
        FFMPEG, "-i", video_path,
        "-vf", f"scdet=threshold={t:.1f}",
        "-f", "null", "-",
    ]
    r1 = subprocess.run(detect_cmd, capture_output=True, text=True)
    timestamps = _parse_scdet(r1.stderr)

    if not timestamps:
        if r1.returncode != 0:
            raise RuntimeError(
                f"ffmpeg scene detection failed (exit {r1.returncode}):\n{r1.stderr[-600:]}"
            )
        raise RuntimeError(
            f"No scene changes detected (threshold={t:.1f}). "
            "Try a lower threshold (e.g. 2.0 for AV1/YouTube videos)."
        )

    logger.info("scdet found %d scene changes at threshold=%.1f; extracting frames…", len(timestamps), t)

    # --- Pass 2: one frame per timestamp, parallelised ---
    def _extract_one(idx: int, ts: float) -> tuple[int, str | None]:
        out_path = os.path.join(session_dir, f"frame_{idx:06d}.jpg")
        pre = max(ts - 3.0, 0.0)
        post = ts - pre
        cmd = [
            FFMPEG,
            "-ss", f"{pre:.3f}",   # fast input-seek ≈3 s before scene change
            "-i", video_path,
            "-ss", f"{post:.3f}",  # accurate output-seek to the exact frame
            "-frames:v", "1",
            "-q:v", "2",
            out_path, "-y",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out_path):
            return idx, out_path
        logger.warning("Frame extraction failed at t=%.3f: %s", ts, r.stderr[-200:])
        return idx, None

    results: dict[int, str | None] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_extract_one, i, ts): i for i, ts in enumerate(timestamps)}
        for future in as_completed(futures):
            idx, path = future.result()
            results[idx] = path

    frames = []
    for i, ts in enumerate(timestamps):
        path = results.get(i)
        if path is not None:
            frames.append({
                "path": path,
                "timestamp": ts,
                "timestamp_str": format_timestamp(ts),
            })

    if not frames:
        raise RuntimeError("Scene changes were detected but no frames could be extracted.")

    return frames


def dedup_frames(frames: list[dict]) -> list[dict]:
    """Drop frames whose pHash is within DEDUP_HASH_THRESHOLD of the previous kept frame."""
    kept: list[dict] = []
    prev_hash = None

    for frame in frames:
        try:
            img = Image.open(frame["path"])
            h = imagehash.phash(img)
        except Exception as e:
            logger.warning("Skipping unreadable frame %s: %s", frame["path"], e)
            continue

        if prev_hash is None or (h - prev_hash) > DEDUP_HASH_THRESHOLD:
            kept.append(frame)
            prev_hash = h
        else:
            try:
                os.remove(frame["path"])
            except OSError:
                pass

    logger.info("Dedup: kept %d / %d frames", len(kept), len(frames))
    return kept


def extract_and_dedup(video_path: str, session_dir: str, threshold: float | None = None) -> list[dict]:
    """Full pipeline: scene detection + dedup + UUID assignment."""
    frames = extract_frames(video_path, session_dir, threshold)
    frames = dedup_frames(frames)
    for f in frames:
        f["id"] = str(uuid.uuid4())
    return frames
