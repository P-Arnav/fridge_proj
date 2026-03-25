import { useEffect, useRef, useState } from 'react'
import { C } from '../constants.js'
import { api } from '../api.js'

export default function ReceiptModal({ onClose }) {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const streamRef = useRef(null)
  const fileInputRef = useRef(null)

  const [mode, setMode] = useState('camera') // 'camera' | 'upload'
  const [status, setStatus] = useState('starting') // starting | ready | scanning | reviewing | adding | done | error
  const [message, setMessage] = useState('')
  const [extractedText, setExtractedText] = useState('')
  const [detectedItems, setDetectedItems] = useState([])
  const [addedCount, setAddedCount] = useState(0)

  // Start Camera
  useEffect(() => {
    if (mode !== 'camera') return
    async function startCamera() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } }
        })
        streamRef.current = stream
        if (videoRef.current) videoRef.current.srcObject = stream
        setStatus('ready')
      } catch (err) {
        setStatus('error')
        setMessage(`Camera error: ${err.message}`)
      }
    }
    startCamera()
    return () => streamRef.current?.getTracks().forEach(t => t.stop())
  }, [mode])

  // Capture Image
  async function captureReceipt() {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas) return

    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d').drawImage(video, 0, 0)
    
    // Convert to Blob and Scan
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9))
    await processReceipt(blob)
  }

  // Handle File Upload
  async function handleFileUpload(e) {
    const file = e.target.files[0]
    if (!file) return
    setStatus('scanning')
    await processReceipt(file)
  }

  // Process Receipt via Backend OCR
  async function processReceipt(blob) {
    setStatus('scanning')
    setMessage('Extracting items from receipt...')
    
    try {
      const result = await api.scanReceipt(blob)
      if (!result.items || result.items.length === 0) {
        setStatus('ready')
        setMessage('No items detected.')
        return
      }
      
      setDetectedItems(result.items)
      setExtractedText(result.raw_text)
      setStatus('reviewing')
      setMessage(`Found ${result.items.length} item(s). Please review.`)
    } catch {
      setStatus('error')
      setMessage('Failed to process receipt.')
    }
  }

  // Add items
  async function completeAdd() {
    setStatus('adding')
    setMessage('Adding items...')
    
    let added = 0
    for (const item of detectedItems) {
      try {
        await api.postItem({
          name: item.name, 
          category: item.category, 
          quantity: item.quantity || 1,
          shelf_life: item.shelf_life, 
          location: '', 
          estimated_cost: item.estimated_cost ?? 0,
          storage_temp: 4.0, 
          humidity: 50.0,
        })
        added++
      } catch { /* ignore */ }
    }

    setAddedCount(added)
    setStatus('done')
    setMessage('')
    setTimeout(onClose, 2500)
  }

  const busy = status === 'scanning' || status === 'adding'

  return (
    <div style={{
      position: 'fixed', inset: 0, background: '#00000099', zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(4px)'
    }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{
        background: C.surface, border: `1px solid ${C.border2}`, borderRadius: 16,
        padding: 24, width: 560, maxWidth: '95vw',
        boxShadow: '0 20px 40px rgba(0,0,0,0.2)'
      }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ fontWeight: 700, fontSize: 18, color: C.text }}>Upload Receipt</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: C.muted, cursor: 'pointer', fontSize: 18 }}>✕</button>
        </div>

        {/* Mode tabs */}
        {status !== 'reviewing' && status !== 'done' && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            {[['camera', 'Take Photo'], ['upload', 'Upload Image']].map(([m, label]) => (
              <button key={m} onClick={() => { setMode(m); setStatus('starting') }} style={{
                background: mode === m ? C.teal + '22' : 'none',
                border: `1px solid ${mode === m ? C.teal : C.border2}`,
                color: mode === m ? C.teal : C.muted,
                borderRadius: 20, padding: '6px 16px', cursor: 'pointer', fontSize: 13,
                fontFamily: "'Syne', sans-serif", fontWeight: mode === m ? 700 : 400,
                transition: 'all 0.2s'
              }}>{label}</button>
            ))}
          </div>
        )}

        {/* Camera/Upload Area */}
        {status !== 'reviewing' && status !== 'done' && (
          <div style={{ position: 'relative', borderRadius: 12, overflow: 'hidden', background: C.surface2, marginBottom: 16, border: `1px dashed ${C.border2}`, height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {mode === 'camera' ? (
              <>
                <video ref={videoRef} autoPlay playsInline muted style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                {status === 'starting' && (
                  <div style={{ position: 'absolute', color: C.muted, fontSize: 14 }}>Starting camera…</div>
                )}
              </>
            ) : (
              <div style={{ textAlign: 'center', color: C.muted }}>
                <div style={{ fontSize: 40, marginBottom: 10 }}>📄</div>
                <div>Select a receipt image</div>
                <input ref={fileInputRef} type="file" accept="image/*" onChange={handleFileUpload} style={{ display: 'none' }} />
                <button onClick={() => fileInputRef.current?.click()} style={{ ...btnPrimary, marginTop: 16 }}>Browse Files</button>
              </div>
            )}
          </div>
        )}
        <canvas ref={canvasRef} style={{ display: 'none' }} />

        {/* Review Area (Multi-Modal Verification Step) */}
        {status === 'reviewing' && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ color: C.teal, fontSize: 14, fontWeight: 700, marginBottom: 8 }}>Detected Items:</div>
            <div style={{ 
              background: C.bg, border: `1px solid ${C.border2}`, borderRadius: 12, 
              padding: 12, maxHeight: 200, overflowY: 'auto' 
            }}>
              {detectedItems.map((i, idx) => (
                <div key={idx} style={{ 
                  display: 'flex', justifyContent: 'space-between', padding: '8px 0',
                  borderBottom: idx < detectedItems.length -1 ? `1px solid ${C.border2}` : 'none'
                }}>
                  <div style={{ color: C.text, fontWeight: 600 }}>{i.quantity}x {i.name}</div>
                  <div style={{ color: C.muted, fontSize: 13 }}>{i.category} • ${i.estimated_cost?.toFixed(2)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Status Messages */}
        {status === 'done' && (
          <div style={{ padding: '30px 0', textAlign: 'center' }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
            <div style={{ color: C.safe, fontSize: 16, fontWeight: 700 }}>
              Added {addedCount} item{addedCount !== 1 ? 's' : ''} from receipt.
            </div>
          </div>
        )}
        {status === 'error' && <div style={{ color: C.critical, fontSize: 14, marginBottom: 16 }}>{message}</div>}
        {busy && <div style={{ color: C.teal, fontSize: 14, marginBottom: 16 }}>{message}</div>}
        {status === 'ready' && message && <div style={{ color: C.safe, fontSize: 14, marginBottom: 16 }}>{message}</div>}

        {/* Action Buttons */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
          <button onClick={onClose} style={btnSecondary}>
            {status === 'done' ? 'Close' : 'Cancel'}
          </button>
          
          {mode === 'camera' && status === 'ready' && (
            <button onClick={captureReceipt} style={btnPrimary}>
              Capture Receipt
            </button>
          )}

          {status === 'reviewing' && (
             <button onClick={completeAdd} style={btnPrimary}>
               Confirm & Add Items
             </button>
          )}
        </div>
      </div>
    </div>
  )
}

const btnPrimary = {
  background: C.teal, color: C.bg, border: 'none', borderRadius: 8,
  padding: '10px 22px', fontWeight: 700, cursor: 'pointer', fontSize: 14,
  fontFamily: "'Syne', sans-serif", transition: 'all 0.2s', boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
}

const btnSecondary = {
  background: 'transparent', color: C.muted, border: `1px solid ${C.border2}`,
  borderRadius: 8, padding: '10px 18px', cursor: 'pointer', fontSize: 14,
  fontFamily: "'Syne', sans-serif", transition: 'all 0.2s'
}
