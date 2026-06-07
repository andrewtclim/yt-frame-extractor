# YT Frame Extractor

Extract scene-change frames from YouTube educational videos, select the ones you want, and export them as a PDF for annotation in Notability.

## Requirements

- **conda env `ytframes`** — Python backend runs inside this env
- **ffmpeg** — must be installed and on PATH (verified at startup)
- **yt-dlp** — must be installed and on PATH (verified at startup)
- **Node.js** (v18+) — for the frontend

## Setup (first time only)

```bash
conda activate ytframes
pip install imagehash Pillow

cd frontend
npm install
```

## Running

```bash
./start.sh
```

This starts the backend and frontend, waits until both are ready, and opens `http://localhost:5173` in your browser. Press `Ctrl+C` to stop both servers.

**Optional — add a shell alias so you can launch from anywhere:**

```bash
echo 'alias ytframes="~/Documents/Projects/yt-frame-extractor/start.sh"' >> ~/.zshrc
source ~/.zshrc
```

Then just type `ytframes`.

### Manual start (if you prefer)

```bash
# Terminal 1 — backend
conda activate ytframes
cd backend && uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

## Usage

1. Paste a YouTube URL and click **Process** (or press Enter).
2. Wait for download + extraction — the status bar shows progress.
3. Click thumbnails to select/deselect frames. A blue border + checkmark indicates selection.
4. Use the **Threshold slider** to adjust how many frames are extracted, then click **Rescan** — the already-downloaded video is reused, no re-download needed.
5. Click **Export N frames as PDF** to download `frames.pdf`.
6. Import into Notability on iPad.

## Tuning

Open `backend/extract.py` and adjust the constants at the top:

| Constant | Default | Effect |
|---|---|---|
| `SCENE_THRESHOLD` | `3.0` | scdet threshold (0–100 scale). Lower = more frames. AV1/YouTube videos: try 2–5. h264 videos: try 5–20. |
| `DEDUP_HASH_THRESHOLD` | `5` | Hamming distance cutoff for duplicate removal. Lower = stricter dedup. |
| `DOWNLOAD_RESOLUTION` | `720` | Max video height in pixels. 720p keeps slide text readable. |

## API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/process` | Download + extract frames; streams ndjson progress |
| `POST` | `/rescan` | Re-extract from cached video with a new threshold |
| `GET` | `/frames/{id}` | Serve a full-resolution frame image |
| `POST` | `/export` | Build and return the PDF |

## Troubleshooting

- **"No scene changes detected"** — lower `SCENE_THRESHOLD` in `extract.py` or drag the slider left. AV1-encoded YouTube videos need values around 2–4.
- **Too many near-identical frames** — raise `SCENE_THRESHOLD` or lower `DEDUP_HASH_THRESHOLD`.
- **"Could not reach backend"** — ensure uvicorn is running on port 8000 with the `ytframes` env active.
- **Download errors** — yt-dlp can fail on age-restricted or members-only videos.
