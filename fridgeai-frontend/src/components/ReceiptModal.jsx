import { useEffect, useRef, useState } from 'react'
import { C } from '../constants.js'
import { api } from '../api.js'

export default function ReceiptModal({ onClose }) {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const streamRef = useRef(null)
  const fileInputRef = useRef(null)
  const verifyInputRef = useRef(null)

  const [mode, setMode] = useState('camera') // 'camera' | 'upload'
  const [status, setStatus] = useState('starting') // starting | ready | scanning | reviewing | adding | done | error
  const [message, setMessage] = useState('')
  const [extractedText, setExtractedText] = useState('')
  const [detectedItems, setDetectedItems] = useState([])
  const [addedCount, setAddedCount] = useState(0)
  const [verifyingIdx, setVerifyingIdx] = useState(null)

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

  // Handle Multi-Modal Verification (MMV)
  async function handleVerifyProduct(e) {
    const file = e.target.files[0]
    const idx = verifyingIdx
    if (!file || idx == null) return
    
    setDetectedItems(prev => prev.map((item, i) => i === idx ? { ...item, verifying: true, verifyFailed: false } : item))
    try {
      const res = await api.scanFridge(file)
      if (res.items && res.items.length > 0) {
        const best = res.items[0]
        setDetectedItems(prev => prev.map((item, i) => i === idx ? { 
          ...item, 
          name: best.name, 
          category: best.category, 
          shelf_life: best.shelf_life || item.shelf_life,
          verified: true, 
          verifying: false 
        } : item))
      } else {
        setDetectedItems(prev => prev.map((item, i) => i === idx ? { ...item, verifyFailed: true, verifying: false } : item))
      }
    } catch {
      setDetectedItems(prev => prev.map((item, i) => i === idx ? { ...item, verifyFailed: true, verifying: false } : item))
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
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(8px)'
    }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="glass-panel" style={{
        padding: 32, width: 620, maxWidth: '95vw',
        animation: 'fadeIn 0.3s ease-out'
      }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div style={{ fontWeight: 700, fontSize: 22, color: C.text }}>Upload Receipt</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#fff', opacity: 0.6, cursor: 'pointer', fontSize: 24, transition: '0.2s' }} onMouseOver={e=>e.target.style.opacity=1} onMouseOut={e=>e.target.style.opacity=0.6}>✕</button>
        </div>

        {/* Mode tabs */}
        {status !== 'reviewing' && status !== 'done' && (
          <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
            {[['camera', 'Take Photo'], ['upload', 'Upload Image']].map(([m, label]) => (
              <button key={m} onClick={() => { setMode(m); setStatus('starting') }} style={{
                background: mode === m ? 'rgba(0, 212, 170, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                border: `1px solid ${mode === m ? C.teal : 'rgba(255, 255, 255, 0.1)'}`,
                color: mode === m ? C.teal : '#cbd5e1',
                borderRadius: 20, padding: '8px 18px', cursor: 'pointer', fontSize: 13,
                fontFamily: "'Inter', sans-serif", fontWeight: mode === m ? 600 : 400,
                transition: 'all 0.2s'
              }}>{label}</button>
            ))}
          </div>
        )}

        {/* Camera/Upload Area */}
        {status !== 'reviewing' && status !== 'done' && (
          <div style={{ position: 'relative', borderRadius: 16, overflow: 'hidden', background: 'rgba(0,0,0,0.3)', marginBottom: 20, border: `1px dashed rgba(255,255,255,0.15)`, height: 340, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {mode === 'camera' ? (
              <>
                <video ref={videoRef} autoPlay playsInline muted style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                {status === 'starting' && (
                  <div style={{ position: 'absolute', color: C.text, fontSize: 14 }}>Starting camera…</div>
                )}
              </>
            ) : (
              <div style={{ textAlign: 'center', color: '#94a3b8' }}>
                <div style={{ fontSize: 48, marginBottom: 12 }}>📄</div>
                <div style={{ marginBottom: 16, fontSize: 15 }}>Select a grocery receipt image</div>
                <input ref={fileInputRef} type="file" accept="image/*" onChange={handleFileUpload} style={{ display: 'none' }} />
                <button className="glass-button-primary" onClick={() => fileInputRef.current?.click()} style={{ padding: '10px 24px' }}>Browse Files</button>
              </div>
            )}
          </div>
        )}
        <canvas ref={canvasRef} style={{ display: 'none' }} />

        {/* hidden verify input */}
        <input ref={verifyInputRef} type="file" accept="image/*,video/*" capture="environment" onChange={handleVerifyProduct} style={{ display: 'none' }} />

        {/* Review Area (Multi-Modal Verification Step) */}
        {status === 'reviewing' && (
          <div style={{ marginBottom: 24 }}>
            <div style={{ color: C.teal, fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Review & Verify Detected Items:</div>
            <div style={{ 
              background: 'rgba(0,0,0,0.2)', border: `1px solid rgba(255,255,255,0.1)`, borderRadius: 12, 
              padding: '6px 12px', maxHeight: 250, overflowY: 'auto' 
            }}>
              {detectedItems.map((item, idx) => (
                <div key={idx} style={{ 
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 0',
                  borderBottom: idx < detectedItems.length -1 ? `1px solid rgba(255,255,255,0.08)` : 'none'
                }}>
                  <div>
                    <div style={{ color: item.verified ? C.safe : C.text, fontWeight: 600, fontSize: 15, display: 'flex', alignItems: 'center', gap: 6 }}>
                      {item.verified && <span>✓</span>} {item.quantity}x {item.name}
                    </div>
                    <div style={{ color: '#94a3b8', fontSize: 13, marginTop: 4 }}>
                      {item.category} • ${item.estimated_cost?.toFixed(2)}
                    </div>
                  </div>
                  <div>
                    {item.verifying ? (
                      <span style={{ color: C.teal, fontSize: 13, animation: 'pulse 1.5s infinite' }}>Verifying...</span>
                    ) : (
                      <button className="glass-button" style={{ 
                        padding: '6px 14px', fontSize: 12, 
                        borderColor: item.verifyFailed ? C.critical : item.verified ? C.safe : 'rgba(255,255,255,0.15)',
                        color: item.verifyFailed ? C.critical : item.verified ? C.safe : '#cbd5e1'
                      }} onClick={() => { setVerifyingIdx(idx); verifyInputRef.current?.click() }}>
                        {item.verified ? 'Verified' : item.verifyFailed ? 'Try Again' : '📷 Verify Image'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 12, lineHeight: 1.4 }}>
              * Multi-Modal Verification (MMV): You can optionally verify OCR results by capturing a photo of the physical product.
            </div>
          </div>
        )}

        {/* Status Messages */}
        {status === 'done' && (
          <div style={{ padding: '40px 0', textAlign: 'center' }}>
            <div style={{ fontSize: 56, marginBottom: 16 }}>✅</div>
            <div style={{ color: C.safe, fontSize: 20, fontWeight: 700 }}>
              Added {addedCount} item{addedCount !== 1 ? 's' : ''} from receipt.
            </div>
          </div>
        )}
        {status === 'error' && <div style={{ color: C.critical, fontSize: 14, marginBottom: 20, background: 'rgba(255, 77, 109, 0.1)', padding: 12, borderRadius: 8 }}>{message}</div>}
        {busy && <div style={{ color: C.teal, fontSize: 14, marginBottom: 20 }}>{message}</div>}
        {status === 'ready' && message && <div style={{ color: C.safe, fontSize: 14, marginBottom: 20 }}>{message}</div>}

        {/* Action Buttons */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
          <button className="glass-button" onClick={onClose} style={{ padding: '10px 20px' }}>
            {status === 'done' ? 'Close' : 'Cancel'}
          </button>
          
          {mode === 'camera' && status === 'ready' && (
            <button className="glass-button-primary" onClick={captureReceipt} style={{ padding: '10px 20px' }}>
              Capture Receipt
            </button>
          )}

          {status === 'reviewing' && (
             <button className="glass-button-primary" onClick={completeAdd} style={{ padding: '10px 20px' }}>
               Confirm & Add Items
             </button>
          )}
        </div>
      </div>
    </div>
  )
}
