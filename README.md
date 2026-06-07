# YT Frame Extractor

Extract scene-change frames from YouTube educational videos, select the ones you want, and export them as a PDF for annotation in Notability.

## Requirements

- **conda env `ytframes`** must be active for the backend
- **ffmpeg** — already expected to be installed (verified at startup)
- **yt-dlp** — already expected to be installed (verified at startup)
- **Node.js** (v18+) for the frontend

## Setup

### 1. Install Python dependencies

```bash
conda activate ytframes
pip install imagehash Pillow
```

> All other backend deps (fastapi, uvicorn, yt-dlp, img2pdf) are already present in the env.

### 2. Start the backend

```bash
conda activate ytframes
cd backend
uvicorn main:app --reload --port 8000
```

The server starts at `http://localhost:8000`. It will exit with a clear error message if `ffmpeg` or `yt-dlp` are missing.

### 3. Start the frontend (separate terminal)

```bash
cd frontend
npm install   # first time only
npm run dev
```

The app opens at `http://localhost:5173`.

## Usage

1. Paste a YouTube URL and click **Process** (or press Enter).
2. Wait for download + extraction — progress is shown in the status bar.
3. Click thumbnails to select/deselect frames. A blue border + checkmark indicates selection.
4. Toggle **Stamp timestamps** (default: on) to embed the video timestamp on each frame in the PDF.
5. Click **Export N frames as PDF** — the file downloads as `frames.pdf`.
6. Import into Notability on iPad.

## Tuning

Open `backend/extract.py` and adjust the constants at the top:

| Constant | Default | Effect |
|---|---|---|
| `SCENE_THRESHOLD` | `0.3` | ffmpeg scene sensitivity. Lower = more frames extracted (more sensitive to small changes). Range: 0.0–1.0. |
| `DEDUP_HASH_THRESHOLD` | `5` | Hamming distance cutoff for duplicate removal. Lower = stricter dedup (fewer frames kept). |
| `DOWNLOAD_RESOLUTION` | `720` | Max video height in pixels for download. Higher = larger files, slower processing. |

## API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/process` | Streams progress + returns extracted frames |
| `GET` | `/frames/{id}` | Serves a full-resolution frame image |
| `POST` | `/export` | Builds and returns the PDF |

## Troubleshooting

- **"No frames extracted"** — lower `SCENE_THRESHOLD` (try `0.2` or `0.15`) in `extract.py`.
- **Too many near-identical frames** — raise `SCENE_THRESHOLD` or lower `DEDUP_HASH_THRESHOLD`.
- **"Could not reach backend"** — ensure uvicorn is running on port 8000 with the `ytframes` env active.
- **Download errors** — yt-dlp can fail on age-restricted or members-only videos.
