import { useEffect, useRef, useState } from 'react'
import { C } from '../constants.js'
import { api } from '../api.js'

export default function MultiScanModal({ onClose }) {
  const [cameras, setCameras]       = useState([])       // [{deviceId, label}]
  const [selected, setSelected]     = useState([])       // deviceIds to use
  const [streams, setStreams]        = useState({})       // {deviceId: MediaStream}
  const [status, setStatus]         = useState('init')   // init | ready | capturing | detecting | review | error
  const [message, setMessage]       = useState('')
  const [result, setResult]         = useState(null)     // MultiScanResult from backend
  const [addedCount, setAddedCount] = useState(0)
  const videoRefs = useRef({})
  const canvasRef = useRef(null)

  // ── Enumerate cameras on mount ──────────────────────────────────────────────
  useEffect(() => {
    async function enumerate() {
      try {
        // Need temporary permission to get labels
        const tempStream = await navigator.mediaDevices.getUserMedia({ video: true })
        tempStream.getTracks().forEach(t => t.stop())

        const devices = await navigator.mediaDevices.enumerateDevices()
        const videoCams = devices
          .filter(d => d.kind === 'videoinput')
          .map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Camera ${i}` }))

        setCameras(videoCams)
        // Auto-select all cameras
        setSelected(videoCams.map(c => c.deviceId))
      } catch (err) {
        setStatus('error')
        setMessage(`Camera access denied: ${err.message}`)
      }
    }
    enumerate()
  }, [])

  // ── Start streams when selection changes ────────────────────────────────────
  useEffect(() => {
    if (selected.length === 0) return

    let cancelled = false
    const activeStreams = {}

    async function startAll() {
      for (const deviceId of selected) {
        if (cancelled) break
        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            video: { deviceId: { exact: deviceId }, width: { ideal: 1280 }, height: { ideal: 720 } },
          })
          activeStreams[deviceId] = stream
          // Stagger camera opens to avoid USB bandwidth contention
          await new Promise(r => setTimeout(r, 500))
        } catch (err) {
          console.warn(`Failed to open camera ${deviceId}:`, err)
        }
      }
      if (!cancelled) {
        setStreams({ ...activeStreams })
        setStatus('ready')
      }
    }

    startAll()

    return () => {
      cancelled = true
      Object.values(activeStreams).forEach(s => s.getTracks().forEach(t => t.stop()))
    }
  }, [selected])

  // ── Assign streams to video elements after render ───────────────────────────
  useEffect(() => {
    for (const [deviceId, stream] of Object.entries(streams)) {
      const video = videoRefs.current[deviceId]
      if (video && video.srcObject !== stream) {
        video.srcObject = stream
      }
    }
  }, [streams])

  // ── Cleanup on unmount ──────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      Object.values(streams).forEach(s => s.getTracks().forEach(t => t.stop()))
    }
  }, [])

  // ── Toggle camera selection ─────────────────────────────────────────────────
  function toggleCamera(deviceId) {
    setSelected(prev =>
      prev.includes(deviceId)
        ? prev.filter(id => id !== deviceId)
        : [...prev, deviceId]
    )
  }

  // ── Capture from all cameras and send to backend ────────────────────────────
  async function captureAndDetect() {
    setStatus('capturing')
    setMessage('Capturing frames...')

    const canvas = canvasRef.current
    const blobs = []

    for (const deviceId of selected) {
      const video = videoRefs.current[deviceId]
      if (!video || video.readyState < 2) continue

      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      canvas.getContext('2d').drawImage(video, 0, 0)

      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.92))
      if (blob) blobs.push(blob)
    }

    if (blobs.length === 0) {
      setStatus('error')
      setMessage('No frames captured. Check camera connections.')
      return
    }

    setStatus('detecting')
    setMessage(`Detecting items across ${blobs.length} camera(s)...`)

    try {
      const res = await api.multiScanFridge(blobs)
      setResult(res)
      setStatus('review')
    } catch (err) {
      setStatus('error')
      setMessage('Detection failed. Check backend connection.')
    }
  }

  // ── Add all detected items to inventory ─────────────────────────────────────
  async function addAllItems() {
    if (!result?.items) return
    const fresh = result.items.filter(i => !i.spoilage_detected)
    setMessage(`Adding ${fresh.length} item(s)...`)

    let added = 0
    for (const item of fresh) {
      try {
        await api.postItem({
          name: item.name,
          category: item.category,
          quantity: item.count,
          shelf_life: item.shelf_life,
          location: '',
          estimated_cost: item.estimated_cost ?? 0,
          storage_temp: 4.0,
          humidity: 50.0,
        })
        added++
      } catch { /* continue */ }
    }

    setAddedCount(added)
    setMessage('')
    setTimeout(onClose, 2000)
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  const cols = Math.min(selected.length, 3) || 1

  return (
    <div style={{
      position: 'fixed', inset: 0, background: '#00000099', zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{
        background: C.surface, border: `1px solid ${C.border2}`, borderRadius: 14,
        padding: 24, width: 720, maxWidth: '95vw', maxHeight: '90vh', overflowY: 'auto',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div style={{ fontWeight: 700, fontSize: 17, color: C.text }}>Multi-Camera Scan</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: C.muted, cursor: 'pointer', fontSize: 18 }}>X</button>
        </div>

        {/* Camera selection */}
        {status !== 'review' && cameras.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 11, color: C.muted, marginBottom: 6, fontFamily: "'Syne', sans-serif", textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Cameras ({cameras.length} found)
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {cameras.map((cam, i) => {
                const active = selected.includes(cam.deviceId)
                return (
                  <button key={cam.deviceId} onClick={() => toggleCamera(cam.deviceId)} style={{
                    background: active ? C.teal + '22' : 'none',
                    border: `1px solid ${active ? C.teal : C.border2}`,
                    color: active ? C.teal : C.muted,
                    borderRadius: 20, padding: '5px 12px', cursor: 'pointer', fontSize: 11,
                    fontFamily: "'Syne', sans-serif", fontWeight: active ? 700 : 400,
                  }}>
                    {cam.label.length > 30 ? cam.label.slice(0, 30) + '...' : cam.label}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {/* Video feeds */}
        {status !== 'review' && selected.length > 0 && (
          <div style={{
            display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 10,
            marginBottom: 14,
          }}>
            {selected.map((deviceId, i) => {
              const cam = cameras.find(c => c.deviceId === deviceId)
              return (
                <div key={deviceId} style={{ position: 'relative', borderRadius: 10, overflow: 'hidden', background: C.surface2 }}>
                  <video
                    ref={el => { if (el) videoRefs.current[deviceId] = el }}
                    autoPlay playsInline muted
                    style={{ width: '100%', display: 'block', maxHeight: 240, objectFit: 'cover' }}
                  />
                  <div style={{
                    position: 'absolute', bottom: 6, left: 8,
                    background: '#000000aa', borderRadius: 4, padding: '2px 8px',
                    color: C.teal, fontSize: 10, fontWeight: 700,
                  }}>
                    CAM {i}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        <canvas ref={canvasRef} style={{ display: 'none' }} />

        {/* Review results */}
        {status === 'review' && result && (
          <div style={{ marginBottom: 14 }}>
            {/* Metrics */}
            <div style={{ display: 'flex', gap: 14, marginBottom: 14 }}>
              <MiniMetric label="Cameras" value={result.cameras_used} color={C.blue} />
              <MiniMetric label="Raw detections" value={result.raw_total} color={C.muted} />
              <MiniMetric label="After dedup" value={result.dedup_total} color={C.teal} />
              <MiniMetric label="Duplicates removed" value={result.raw_total - result.dedup_total} color={C.warn} />
            </div>

            {/* Items table */}
            <div style={{ background: C.surface2, borderRadius: 10, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
              <div style={{ display: 'flex', padding: '8px 14px', borderBottom: `1px solid ${C.border}`, fontSize: 10, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.08em', fontFamily: "'Syne', sans-serif" }}>
                <div style={{ flex: 1 }}>Item</div>
                <div style={{ width: 60, textAlign: 'center' }}>Count</div>
                <div style={{ width: 80, textAlign: 'center' }}>Category</div>
                <div style={{ width: 70, textAlign: 'center' }}>Confidence</div>
                <div style={{ width: 70, textAlign: 'center' }}>Spoilage</div>
              </div>
              {result.items.map(item => (
                <div key={item.name} style={{
                  display: 'flex', padding: '8px 14px', borderBottom: `1px solid ${C.border}08`,
                  fontSize: 13, color: item.spoilage_detected ? C.critical : C.text,
                }}>
                  <div style={{ flex: 1 }}>{item.name}{item.spoilage_detected ? ' (spoiled)' : ''}</div>
                  <div style={{ width: 60, textAlign: 'center', color: C.teal, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{item.count}</div>
                  <div style={{ width: 80, textAlign: 'center', color: C.muted, fontSize: 11 }}>{item.category}</div>
                  <div style={{ width: 70, textAlign: 'center', color: C.muted, fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}>{Math.round(item.confidence * 100)}%</div>
                  <div style={{ width: 70, textAlign: 'center', fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: item.spoilage_detected ? C.critical : C.safe }}>
                    {item.spoilage_confidence > 0 ? `${Math.round(item.spoilage_confidence * 100)}%` : '--'}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ fontSize: 10, color: C.muted, marginTop: 6, fontFamily: "'Syne', sans-serif" }}>
              Engine: {result.engine}
            </div>
          </div>
        )}

        {/* Added confirmation */}
        {addedCount > 0 && (
          <div style={{ color: C.safe, fontSize: 14, textAlign: 'center', fontWeight: 600, marginBottom: 12 }}>
            Added {addedCount} item type(s) to inventory!
          </div>
        )}

        {/* Status messages */}
        {(status === 'capturing' || status === 'detecting') && (
          <div style={{ color: C.teal, fontSize: 13, marginBottom: 12 }}>{message}</div>
        )}
        {status === 'error' && (
          <div style={{ color: C.critical, fontSize: 13, marginBottom: 12 }}>{message}</div>
        )}
        {status === 'init' && cameras.length === 0 && (
          <div style={{ color: C.muted, fontSize: 13, marginBottom: 12 }}>Looking for cameras...</div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button onClick={onClose} style={btnSecondary}>
            {addedCount > 0 ? 'Done' : 'Cancel'}
          </button>

          {status === 'review' && !addedCount && (
            <>
              <button onClick={() => { setResult(null); setStatus('ready') }} style={btnSecondary}>
                Re-scan
              </button>
              <button onClick={addAllItems} style={btnPrimary}>
                Add {result.items.filter(i => !i.spoilage_detected).length} Fresh Items
              </button>
            </>
          )}

          {(status === 'ready' || status === 'error') && (
            <button
              onClick={captureAndDetect}
              disabled={selected.length === 0}
              style={{ ...btnPrimary, opacity: selected.length === 0 ? 0.5 : 1 }}
            >
              Capture & Detect ({selected.length} cam{selected.length !== 1 ? 's' : ''})
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function MiniMetric({ label, value, color }) {
  return (
    <div style={{
      flex: 1, background: C.surface2, border: `1px solid ${C.border}`,
      borderRadius: 8, padding: '10px 12px', textAlign: 'center',
    }}>
      <div style={{ fontSize: 20, fontWeight: 800, color, fontFamily: "'Syne', sans-serif" }}>{value}</div>
      <div style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.08em', fontFamily: "'Syne', sans-serif", marginTop: 2 }}>{label}</div>
    </div>
  )
}

const btnPrimary = {
  background: C.teal, color: C.bg, border: 'none', borderRadius: 8,
  padding: '9px 20px', fontWeight: 700, cursor: 'pointer', fontSize: 13,
  fontFamily: "'Syne', sans-serif",
}

const btnSecondary = {
  background: 'none', color: C.muted, border: `1px solid ${C.border2}`,
  borderRadius: 8, padding: '9px 16px', cursor: 'pointer', fontSize: 13,
  fontFamily: "'Syne', sans-serif",
}
