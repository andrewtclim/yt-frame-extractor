import { useState } from 'react'
import './App.css'

const API = 'http://localhost:8000'
const DEFAULT_THRESHOLD = 3

export default function App() {
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState('idle') // idle|downloading|extracting|scanning|done|error
  const [frames, setFrames] = useState([])
  const [selected, setSelected] = useState(new Set())
  const [stampTs, setStampTs] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')
  const [exporting, setExporting] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD)

  // Shared stream reader for /process and /rescan responses.
  // onEvent(data) is called for every parsed JSON line.
  async function readStream(res, onEvent) {
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    const pump = async () => {
      const { done, value } = await reader.read()
      if (done) return
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        if (!line.trim()) continue
        try { onEvent(JSON.parse(line)) } catch { /* ignore malformed */ }
      }
      await pump()
    }
    await pump()
  }

  async function handleProcess() {
    if (!url.trim()) return
    setStatus('downloading')
    setFrames([])
    setSelected(new Set())
    setSessionId(null)
    setErrorMsg('')
    setThreshold(DEFAULT_THRESHOLD)

    let res
    try {
      res = await fetch(`${API}/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim() }),
      })
    } catch {
      setErrorMsg('Could not reach backend. Is uvicorn running on port 8000?')
      setStatus('error')
      return
    }

    try {
      await readStream(res, data => {
        if (data.status === 'extracting') {
          setStatus('extracting')
        } else if (data.status === 'done') {
          setFrames(data.frames)
          setSessionId(data.session_id)
          setStatus('done')
        } else if (data.status === 'error') {
          setErrorMsg(data.message)
          setStatus('error')
        }
      })
    } catch (e) {
      setErrorMsg(String(e))
      setStatus('error')
    }
  }

  async function handleRescan() {
    if (!sessionId) return
    setStatus('scanning')
    setSelected(new Set())
    setErrorMsg('')

    let res
    try {
      res = await fetch(`${API}/rescan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, threshold }),
      })
      if (!res.ok) {
        const msg = await res.text()
        throw new Error(msg)
      }
    } catch (e) {
      setErrorMsg(String(e))
      setStatus('error')
      return
    }

    try {
      await readStream(res, data => {
        if (data.status === 'done') {
          setFrames(data.frames)
          setStatus('done')
        } else if (data.status === 'error') {
          setErrorMsg(data.message)
          setStatus('error')
        }
      })
    } catch (e) {
      setErrorMsg(String(e))
      setStatus('error')
    }
  }

  function toggleFrame(id) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function selectAll() { setSelected(new Set(frames.map(f => f.id))) }
  function selectNone() { setSelected(new Set()) }

  async function handleExport() {
    if (selected.size === 0) return
    setExporting(true)
    try {
      const orderedIds = frames.filter(f => selected.has(f.id)).map(f => f.id)
      const res = await fetch(`${API}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ frame_ids: orderedIds, stamp_timestamps: stampTs }),
      })
      if (!res.ok) throw new Error(`Export failed: ${res.status} ${await res.text()}`)
      const blob = await res.blob()
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = 'frames.pdf'
      link.click()
      URL.revokeObjectURL(link.href)
    } catch (e) {
      alert(String(e))
    } finally {
      setExporting(false)
    }
  }

  const busy = status === 'downloading' || status === 'extracting' || status === 'scanning'

  const statusLabel = {
    downloading: 'Downloading video…',
    extracting:  'Extracting scene-change frames…',
    scanning:    `Rescanning at threshold ${threshold}…`,
    done:        `${frames.length} frame${frames.length !== 1 ? 's' : ''} extracted`,
    error:       errorMsg,
  }[status]

  return (
    <div className="app">
      <h1>YT Frame Extractor</h1>

      <div className="input-row">
        <input
          className="url-input"
          value={url}
          onChange={e => setUrl(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !busy && handleProcess()}
          placeholder="Paste a YouTube URL…"
          disabled={busy}
        />
        <button className="btn-primary" onClick={handleProcess} disabled={!url.trim() || busy}>
          {busy && (status === 'downloading' || status === 'extracting') ? '…' : 'Process'}
        </button>
      </div>

      {status !== 'idle' && (
        <p className={`status-bar ${status === 'error' ? 'status-error' : busy ? 'status-busy' : 'status-ok'}`}>
          {busy && <span className="spinner" />}
          {statusLabel}
        </p>
      )}

      {(frames.length > 0 || status === 'scanning') && (
        <div className="sensitivity-bar">
          <span className="sens-label">Threshold</span>
          <span className="sens-hint">more frames</span>
          <input
            type="range"
            className="sens-slider"
            min="1" max="20" step="1"
            value={threshold}
            onChange={e => setThreshold(Number(e.target.value))}
            disabled={busy}
          />
          <span className="sens-hint">fewer frames</span>
          <span className="sens-value">{threshold}</span>
          <button
            className="btn-ghost"
            onClick={handleRescan}
            disabled={busy || !sessionId}
          >
            {status === 'scanning' ? <><span className="spinner" /> Scanning…</> : 'Rescan'}
          </button>
        </div>
      )}

      {frames.length > 0 && (
        <>
          <div className="toolbar">
            <div className="toolbar-left">
              <button className="btn-ghost" onClick={selectAll}>Select all</button>
              <button className="btn-ghost" onClick={selectNone}>Select none</button>
              <label className="stamp-label">
                <input
                  type="checkbox"
                  checked={stampTs}
                  onChange={e => setStampTs(e.target.checked)}
                />
                Stamp timestamps
              </label>
            </div>
            <button
              className="btn-primary"
              onClick={handleExport}
              disabled={selected.size === 0 || exporting}
            >
              {exporting
                ? 'Building PDF…'
                : `Export ${selected.size} frame${selected.size !== 1 ? 's' : ''} as PDF`}
            </button>
          </div>

          <div className="grid">
            {frames.map(f => (
              <div
                key={f.id}
                className={`frame-card${selected.has(f.id) ? ' selected' : ''}`}
                onClick={() => toggleFrame(f.id)}
              >
                {selected.has(f.id) && <div className="check-badge">✓</div>}
                <img
                  src={`${API}${f.thumbnail_url}`}
                  alt={f.timestamp_str}
                  loading="lazy"
                />
                <span className="ts-label">{f.timestamp_str}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
