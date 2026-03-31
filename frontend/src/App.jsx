import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const API_ENDPOINT = import.meta.env.VITE_API_ENDPOINT || '/api/process'
const AUTO_DEBOUNCE_MS = 320

const PROCESS_STEPS = [
  'Upload received',
  'Parsing vector paths',
  'Detecting sharp corners',
  'Rendering output SVG',
]

const DEFAULT_PARAMS = {
  angleThreshold: 45,
  samplesPerCurve: 25,
  markerRadius: 14,
  minSegmentLength: 1,
  cornerRadius: 18,
  radiusProfile: 'vectorizer',
  debug: false,
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
}

function normalizeParams(params) {
  return {
    angleThreshold: clamp(Number(params.angleThreshold) || 0, 0, 180),
    samplesPerCurve: clamp(Math.round(Number(params.samplesPerCurve) || 2), 2, 120),
    markerRadius: clamp(Number(params.markerRadius) || 0.5, 0.5, 32),
    minSegmentLength: clamp(Number(params.minSegmentLength) || 0, 0, 30),
    cornerRadius: clamp(Number(params.cornerRadius) || 0, 0, 120),
    radiusProfile: params.radiusProfile === 'vectorizer' ? 'vectorizer' : 'fixed',
    debug: Boolean(params.debug),
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function buildSvgBlobUrl(svgText) {
  if (!svgText) return ''
  const blob = new Blob([svgText], { type: 'image/svg+xml;charset=utf-8' })
  return URL.createObjectURL(blob)
}

/** Extract viewBox numbers from SVG text. */
function parseSvgViewBox(svgText) {
  if (!svgText) return null
  const m = svgText.match(/viewBox="([^"]*)"/)
  if (!m) return null
  const parts = m[1].trim().split(/[\s,]+/).map(Number)
  if (parts.length < 4 || parts.some(isNaN)) return null
  return { vx: parts[0], vy: parts[1], vw: parts[2], vh: parts[3] }
}

/**
 * Expand the original SVG viewBox so its aspect ratio matches the container.
 * This lets us use preserveAspectRatio="none" without distorting the content —
 * the "letterbox" areas just show the SVG background.
 */
function computeFitViewBox(origVb, containerW, containerH) {
  const { vx: vx0, vy: vy0, vw: vw0, vh: vh0 } = origVb
  const caR = containerW / containerH
  const svgR = vw0 / vh0
  if (caR > svgR) {
    const nw = vh0 * caR
    return { vx: vx0 - (nw - vw0) / 2, vy: vy0, vw: nw, vh: vh0 }
  } else {
    const nh = vw0 / caR
    return { vx: vx0, vy: vy0 - (nh - vh0) / 2, vw: vw0, vh: nh }
  }
}

/**
 * Return a modified SVG string suitable for inline rendering:
 * - strips the XML declaration and DOCTYPE
 * - overrides viewBox with the current pan/zoom viewBox
 * - sets width/height to 100% and preserveAspectRatio to none
 */
function buildInlineSvg(svgText, { vx, vy, vw, vh }) {
  return svgText
    .replace(/<\?xml[^?]*\?>\s*/i, '')
    .replace(/<!DOCTYPE[^>]*>\s*/i, '')
    .replace(/viewBox="[^"]*"/, `viewBox="${vx} ${vy} ${vw} ${vh}"`)
    .replace(/<svg([^>]*)>/i, (_, attrs) => {
      const a = attrs
        .replace(/\s+width="[^"]*"/g, '')
        .replace(/\s+height="[^"]*"/g, '')
        .replace(/\s+preserveAspectRatio="[^"]*"/g, '')
      return `<svg${a} width="100%" height="100%" preserveAspectRatio="none">`
    })
}

function App() {
  const [params, setParams] = useState(DEFAULT_PARAMS)
  const [inputFile, setInputFile] = useState(null)
  const [originalSvgText, setOriginalSvgText] = useState('')
  const [processedSvgText, setProcessedSvgText] = useState('')
  const [processedRevision, setProcessedRevision] = useState(0)
  const [corners, setCorners] = useState([])
  const [stats, setStats] = useState(null)
  const [errorText, setErrorText] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)
  const [progress, setProgress] = useState(0)
  const [progressStep, setProgressStep] = useState(0)
  const [liveEnabled, setLiveEnabled] = useState(true)
  const [workflow, setWorkflow] = useState('markers')
  const [downloadPulse, setDownloadPulse] = useState(false)
  const [viewInputOpen, setViewInputOpen] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [svgViewBox, setSvgViewBox] = useState(null)   // current pan/zoom viewBox
  const [cornerRadiusOverrides, setCornerRadiusOverrides] = useState({}) // "pathId:nodeId" → radius

  const normalizedParams = useMemo(() => normalizeParams(params), [params])
  const canProcess = Boolean(inputFile)
  const modeLabel = workflow === 'round' ? 'Arc mode' : workflow === 'preview_arcs' ? 'Arc preview mode' : 'Sharp-corner marker mode'

  const originalPreviewUrl = useMemo(() => buildSvgBlobUrl(originalSvgText), [originalSvgText])

  const progressTimerRef = useRef(null)
  const autoDebounceRef = useRef(null)
  const abortRef = useRef(null)
  const requestIdRef = useRef(0)
  const workflowRef = useRef(workflow)
  workflowRef.current = workflow
  const frameRef = useRef(null)
  const dragStartRef = useRef(null)   // { mx, my, vb: {...} }
  const origViewBoxRef = useRef(null) // viewBox of the original (fit) state for reset

  useEffect(() => {
    return () => {
      if (progressTimerRef.current !== null) window.clearInterval(progressTimerRef.current)
      if (autoDebounceRef.current !== null) window.clearTimeout(autoDebounceRef.current)
      if (abortRef.current) abortRef.current.abort()
      if (originalPreviewUrl) URL.revokeObjectURL(originalPreviewUrl)
    }
  }, [originalPreviewUrl])

  // When a new processed SVG arrives, compute the fit viewBox and reset view
  useEffect(() => {
    const origVb = parseSvgViewBox(processedSvgText)
    if (!origVb) { setSvgViewBox(null); origViewBoxRef.current = null; return }
    const frame = frameRef.current
    const { width: cw, height: ch } = frame
      ? frame.getBoundingClientRect()
      : { width: origVb.vw, height: origVb.vh }
    const fitVb = computeFitViewBox(origVb, cw || origVb.vw, ch || origVb.vh)
    origViewBoxRef.current = fitVb
    setSvgViewBox(fitVb)
  }, [processedSvgText])

  // Non-passive wheel: zoom centred on cursor by shrinking/expanding the viewBox
  useEffect(() => {
    const frame = frameRef.current
    if (!frame) return
    const onWheel = (e) => {
      e.preventDefault()
      const { left, top, width: cw, height: ch } = frame.getBoundingClientRect()
      const mx = e.clientX - left
      const my = e.clientY - top
      const factor = e.deltaY < 0 ? 1 / 1.13 : 1.13   // scroll up = zoom in = smaller vw
      setSvgViewBox((vb) => {
        if (!vb) return vb
        const { vx, vy, vw, vh } = vb
        const newVw = Math.min(Math.max(vw * factor, vw * 0.001), vw * 80)
        const newVh = Math.min(Math.max(vh * factor, vh * 0.001), vh * 80)
        // Keep the SVG point under the cursor fixed
        const svgX = vx + mx * (vw / cw)
        const svgY = vy + my * (vh / ch)
        return {
          vx: svgX - mx * (newVw / cw),
          vy: svgY - my * (newVh / ch),
          vw: newVw,
          vh: newVh,
        }
      })
    }
    frame.addEventListener('wheel', onWheel, { passive: false })
    return () => frame.removeEventListener('wheel', onWheel)
  }, [])

  // Global mousemove/mouseup so drag stays smooth when cursor leaves the frame
  useEffect(() => {
    const onMove = (e) => {
      if (!dragStartRef.current) return
      const { mx, my, vb } = dragStartRef.current
      const frame = frameRef.current
      if (!frame) return
      const { width: cw, height: ch } = frame.getBoundingClientRect()
      const dx = e.clientX - mx
      const dy = e.clientY - my
      setSvgViewBox({
        vx: vb.vx - dx * (vb.vw / cw),
        vy: vb.vy - dy * (vb.vh / ch),
        vw: vb.vw,
        vh: vb.vh,
      })
    }
    const onUp = () => {
      if (!dragStartRef.current) return
      dragStartRef.current = null
      setIsDragging(false)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  function startDrag(e) {
    if (e.button !== 0 || !svgViewBox) return
    e.preventDefault()
    setIsDragging(true)
    dragStartRef.current = { mx: e.clientX, my: e.clientY, vb: { ...svgViewBox } }
  }

  function resetZoom() {
    if (origViewBoxRef.current) setSvgViewBox({ ...origViewBoxRef.current })
  }

  function updateParam(name, value) {
    setParams((previous) => ({
      ...previous,
      [name]: value,
    }))
  }

  function onFileChange(event) {
    const file = event.target.files?.[0]
    setErrorText('')
    setProcessedSvgText('')
    setCorners([])
    setStats(null)
    setProgress(0)
    setProgressStep(0)
    setCornerRadiusOverrides({})

    if (!file) {
      setInputFile(null)
      setOriginalSvgText('')
      return
    }

    if (!file.name.toLowerCase().endsWith('.svg')) {
      setInputFile(null)
      setOriginalSvgText('')
      setErrorText('Please upload an SVG file.')
      return
    }

    const reader = new FileReader()
    reader.onload = () => {
      setInputFile(file)
      setOriginalSvgText(typeof reader.result === 'string' ? reader.result : '')
    }
    reader.onerror = () => {
      setInputFile(null)
      setOriginalSvgText('')
      setErrorText('Could not read the selected file.')
    }
    reader.readAsText(file)
  }

  function stopProgressAnimation() {
    if (progressTimerRef.current !== null) {
      window.clearInterval(progressTimerRef.current)
      progressTimerRef.current = null
    }
  }

  function startProgressAnimation() {
    stopProgressAnimation()
    setProgress(0)
    setProgressStep(0)

    progressTimerRef.current = window.setInterval(() => {
      setProgress((previous) => {
        const next = previous >= 90 ? previous : previous + (Math.random() * 7 + 2)
        const clamped = clamp(next, 0, 90)
        setProgressStep(Math.min(PROCESS_STEPS.length - 1, Math.floor(clamped / 25)))
        return clamped
      })
    }, 130)
  }

  function finishProgressAnimation() {
    stopProgressAnimation()
    setProgress(100)
    setProgressStep(PROCESS_STEPS.length - 1)
  }

  function makeFormData(mode, overrides = {}) {
    const form = new FormData()
    form.append('file', inputFile)
    form.append('angleThreshold', String(normalizedParams.angleThreshold))
    form.append('samplesPerCurve', String(normalizedParams.samplesPerCurve))
    form.append('markerRadius', String(normalizedParams.markerRadius))
    form.append('minSegmentLength', String(normalizedParams.minSegmentLength))
    form.append('radiusProfile', normalizedParams.radiusProfile)
    form.append('debug', String(normalizedParams.debug))

    if (mode === 'preview_arcs') {
      form.append('previewArcs', 'true')
      form.append('applyRounding', 'false')
      form.append('cornerRadius', String(normalizedParams.cornerRadius))
      if (Object.keys(overrides).length > 0) {
        form.append('cornerRadiusOverridesJson', JSON.stringify(overrides))
      }
    } else if (mode === 'round') {
      form.append('applyRounding', 'true')
      form.append('cornerRadius', String(normalizedParams.cornerRadius))
      if (Object.keys(overrides).length > 0) {
        form.append('cornerRadiusOverridesJson', JSON.stringify(overrides))
      }
    } else {
      // Marker mode: animated sonar-ping dots only.
      form.append('applyRounding', 'false')
      form.append('cornerRadius', '0')
    }

    return form
  }

  async function runWorkflow(mode, { autoDownload = false, overrides = {} } = {}) {
    if (!canProcess || !inputFile) return
    if (mode === 'round' && normalizedParams.cornerRadius <= 0 && Object.keys(overrides).length === 0) {
      setErrorText('Set Corner Radius above 0 before applying arc rounding.')
      return
    }

    setWorkflow(mode)
    setErrorText('')
    setIsProcessing(true)
    startProgressAnimation()

    const currentRequestId = requestIdRef.current + 1
    requestIdRef.current = currentRequestId

    if (abortRef.current) {
      abortRef.current.abort()
    }
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const response = await fetch(API_ENDPOINT, {
        method: 'POST',
        body: makeFormData(mode, overrides),
        signal: controller.signal,
      })
      const payload = await response.json()

      if (currentRequestId !== requestIdRef.current) return
      if (!response.ok) {
        throw new Error(payload.error || 'Processing failed.')
      }

      setProcessedSvgText(payload.processedSvg || '')
      setProcessedRevision((previous) => previous + 1)
      setCorners(payload.corners || [])
      setStats({
        cornerCount: payload.cornerCount ?? 0,
        pathCount: payload.pathCount ?? 0,
        updatedPathCount: payload.updatedPathCount ?? 0,
        mode: payload.mode || (mode === 'round' ? 'rounded' : 'marked'),
        radiusProfile: payload.radiusProfile || normalizedParams.radiusProfile,
      })

      finishProgressAnimation()

      if (autoDownload && payload.processedSvg) {
        const blob = new Blob([payload.processedSvg], { type: 'image/svg+xml;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = 'finalized_output.svg'
        anchor.click()
        URL.revokeObjectURL(url)
        setDownloadPulse(true)
        window.setTimeout(() => setDownloadPulse(false), 600)
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        stopProgressAnimation()
        return
      }
      const message = error instanceof Error ? error.message : 'Unexpected error.'
      setErrorText(message)
    } finally {
      if (currentRequestId === requestIdRef.current) {
        window.setTimeout(() => {
          setIsProcessing(false)
        }, 180)
      } else {
        stopProgressAnimation()
      }
    }
  }

  const cornerRadiusOverridesRef = useRef(cornerRadiusOverrides)
  cornerRadiusOverridesRef.current = cornerRadiusOverrides

  useEffect(() => {
    if (!liveEnabled || !canProcess) return

    if (workflowRef.current === 'round' && normalizedParams.cornerRadius <= 0) {
      return
    }

    if (autoDebounceRef.current !== null) {
      window.clearTimeout(autoDebounceRef.current)
    }

    autoDebounceRef.current = window.setTimeout(() => {
      runWorkflow(workflowRef.current, { overrides: cornerRadiusOverridesRef.current })
    }, AUTO_DEBOUNCE_MS)

    return () => {
      if (autoDebounceRef.current !== null) {
        window.clearTimeout(autoDebounceRef.current)
      }
    }
  }, [liveEnabled, canProcess, normalizedParams, inputFile, cornerRadiusOverrides])

  function downloadProcessedSvg() {
    if (!processedSvgText) return
    const blob = new Blob([processedSvgText], { type: 'image/svg+xml;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = workflow === 'round' ? 'rounded_output.svg' : 'marked_output.svg'
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className={`app ${isProcessing ? 'processing' : ''}`}>

      {/* ── View Input Modal ── */}
      {viewInputOpen && (
        <div className="input-modal" onClick={() => setViewInputOpen(false)}>
          <button className="modal-close" onClick={() => setViewInputOpen(false)}>✕ Close</button>
          <div className="modal-svg-frame" onClick={(e) => e.stopPropagation()}>
            {originalPreviewUrl
              ? <img src={originalPreviewUrl} alt="Original SVG" />
              : <p className="empty">No input SVG loaded</p>
            }
          </div>
        </div>
      )}

      {/* ── Header ── */}
      <header className="topbar">
        <div className="topbar-title">
          <h1>SVG Corner Studio</h1>
          <p>Detect sharp corners and apply arc rounding</p>
        </div>
        <div className="status-chip">
          <span>{modeLabel}</span>
          <strong>Live {liveEnabled ? 'ON' : 'OFF'}</strong>
        </div>
      </header>

      {/* ── Sidebar ── */}
      <aside className="sidebar">

        {/* File */}
        <div className="panel">
          <div className="panel-header">
            <h2>File</h2>
          </div>
          <div className="file-row">
            <label className="file-input-label">
              <input type="file" accept=".svg,image/svg+xml" onChange={onFileChange} />
              <span>Choose SVG</span>
            </label>
            <div className="file-meta">
              {inputFile ? (
                <>
                  <strong>{inputFile.name}</strong>
                  <span>{formatFileSize(inputFile.size)}</span>
                </>
              ) : (
                <span style={{ color: '#9ca3af', fontSize: '0.82rem' }}>No file selected</span>
              )}
            </div>
          </div>

          <div className="switch-row">
            <label className="toggle">
              <input type="checkbox" checked={liveEnabled} onChange={(e) => setLiveEnabled(e.target.checked)} />
              <span>Live update</span>
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={normalizedParams.debug}
                onChange={(e) => updateParam('debug', e.target.checked)}
              />
              <span>Debug labels</span>
            </label>
          </div>
        </div>

        <div className="section-divider" />

        {/* Parameters */}
        <div className="panel">
          <div className="panel-header">
            <h2>Parameters</h2>
          </div>
          <div className="params-list">

            <div className="param">
              <div className="param-head">
                <label htmlFor="angleThreshold">Angle Threshold</label>
                <input
                  id="angleThreshold"
                  type="number"
                  min="0" max="180" step="1"
                  value={normalizedParams.angleThreshold}
                  onChange={(e) => updateParam('angleThreshold', Number(e.target.value))}
                />
              </div>
              <input
                type="range"
                min="0" max="180" step="1"
                value={normalizedParams.angleThreshold}
                onChange={(e) => updateParam('angleThreshold', Number(e.target.value))}
              />
            </div>

            <div className="param">
              <div className="param-head">
                <label htmlFor="samplesPerCurve">Samples Per Curve</label>
                <input
                  id="samplesPerCurve"
                  type="number"
                  min="2" max="120" step="1"
                  value={normalizedParams.samplesPerCurve}
                  onChange={(e) => updateParam('samplesPerCurve', Number(e.target.value))}
                />
              </div>
              <input
                type="range"
                min="2" max="120" step="1"
                value={normalizedParams.samplesPerCurve}
                onChange={(e) => updateParam('samplesPerCurve', Number(e.target.value))}
              />
            </div>

            <div className="param">
              <div className="param-head">
                <label htmlFor="minSegmentLength">Min Segment Length</label>
                <input
                  id="minSegmentLength"
                  type="number"
                  min="0" max="30" step="0.1"
                  value={normalizedParams.minSegmentLength}
                  onChange={(e) => updateParam('minSegmentLength', Number(e.target.value))}
                />
              </div>
              <input
                type="range"
                min="0" max="30" step="0.1"
                value={normalizedParams.minSegmentLength}
                onChange={(e) => updateParam('minSegmentLength', Number(e.target.value))}
              />
            </div>

            <div className="param">
              <div className="param-head">
                <label htmlFor="markerRadius">Marker Radius</label>
                <input
                  id="markerRadius"
                  type="number"
                  min="0.5" max="32" step="0.5"
                  value={normalizedParams.markerRadius}
                  onChange={(e) => updateParam('markerRadius', Number(e.target.value))}
                />
              </div>
              <input
                type="range"
                min="0.5" max="32" step="0.5"
                value={normalizedParams.markerRadius}
                onChange={(e) => updateParam('markerRadius', Number(e.target.value))}
              />
            </div>

            <div className="param">
              <div className="param-head">
                <label htmlFor="cornerRadius">Corner Radius</label>
                <input
                  id="cornerRadius"
                  type="number"
                  min="0" max="120" step="0.5"
                  value={normalizedParams.cornerRadius}
                  onChange={(e) => updateParam('cornerRadius', Number(e.target.value))}
                />
              </div>
              <input
                type="range"
                min="0" max="120" step="0.5"
                value={normalizedParams.cornerRadius}
                onChange={(e) => updateParam('cornerRadius', Number(e.target.value))}
              />
            </div>

            <div className="param">
              <div className="param-head">
                <label htmlFor="radiusProfile">Radius Profile</label>
                <select
                  id="radiusProfile"
                  value={normalizedParams.radiusProfile}
                  onChange={(e) => updateParam('radiusProfile', e.target.value)}
                >
                  <option value="fixed">Fixed</option>
                  <option value="vectorizer">Vectorizer</option>
                </select>
              </div>
              <small>Vectorizer adapts radius per corner angle</small>
            </div>

          </div>
        </div>

        <div className="section-divider" />

        {/* Actions */}
        <div className="panel">
          <div className="panel-header">
            <h2>Actions</h2>
          </div>
          <div className="action-row">
            <button
              className="primary-button"
              type="button"
              disabled={!canProcess || isProcessing}
              onClick={() => runWorkflow('markers')}
            >
              Find Sharp Corners
            </button>
            <button
              className="secondary-button"
              type="button"
              disabled={!canProcess || isProcessing || normalizedParams.cornerRadius <= 0}
              onClick={() => runWorkflow('preview_arcs', { overrides: cornerRadiusOverrides })}
            >
              Preview Arc Circles
            </button>
            <button
              className="secondary-button"
              type="button"
              disabled={!canProcess || isProcessing || normalizedParams.cornerRadius <= 0}
              onClick={() => runWorkflow('round', { overrides: cornerRadiusOverrides })}
              style={{ background: '#7c3aed' }}
            >
              Apply Arc Rounding
            </button>
            <button
              className="finalize-button"
              type="button"
              disabled={!canProcess || isProcessing || normalizedParams.cornerRadius <= 0}
              onClick={() => runWorkflow('round', { autoDownload: true, overrides: cornerRadiusOverrides })}
            >
              Finalize &amp; Download
            </button>
            <button
              className="ghost-button"
              type="button"
              disabled={!processedSvgText}
              onClick={downloadProcessedSvg}
            >
              Download Current
            </button>
          </div>
          {(workflow === 'round' || workflow === 'preview_arcs') && normalizedParams.cornerRadius <= 0 && (
            <p className="warn">Set Corner Radius &gt; 0 to use arc rounding.</p>
          )}
          {errorText && <p className="error">{errorText}</p>}
        </div>

        {/* Progress — pinned to bottom of sidebar */}
        <div style={{ flex: 1 }} />
        <div className="progress-panel">
          <span className="progress-label">Progress</span>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
          <ul className="step-list">
            {PROCESS_STEPS.map((step, index) => {
              const state = index < progressStep ? 'done' : index === progressStep && isProcessing ? 'active' : ''
              return (
                <li key={step} className={state}>
                  <span className="dot" />
                  <span>{step}</span>
                </li>
              )
            })}
          </ul>
        </div>

      </aside>

      {/* ── Main ── */}
      <div className="main-area">

        {/* Single output pane */}
        <div className={`preview-pane ${downloadPulse ? 'finalized' : ''}`}>
          <div className="pane-header">
            <h2>Output</h2>
            <div className="pane-actions">
              {stats && (
                <div className="summary">
                  <span>{stats.cornerCount} corners</span>
                  <span>{stats.pathCount} paths</span>
                  <span>{stats.mode}</span>
                  <span>{stats.radiusProfile}</span>
                </div>
              )}
              {inputFile && (
                <button
                  className="view-input-btn"
                  type="button"
                  onClick={() => setViewInputOpen(true)}
                >
                  View Input
                </button>
              )}
            </div>
          </div>
          <div
            className="svg-frame"
            ref={frameRef}
            onMouseDown={startDrag}
            onDoubleClick={resetZoom}
            style={{ cursor: isDragging ? 'grabbing' : (svgViewBox ? 'grab' : 'default') }}
          >
            {processedSvgText && svgViewBox ? (
              <div
                key={processedRevision}
                className={isProcessing ? 'is-updating' : ''}
                style={{ width: '100%', height: '100%', userSelect: 'none', pointerEvents: 'none' }}
                dangerouslySetInnerHTML={{ __html: buildInlineSvg(processedSvgText, svgViewBox) }}
              />
            ) : (
              <p className="empty">
                {inputFile
                  ? 'Click "Find Sharp Corners" or "Add Arc Rounding" to process'
                  : 'Upload an SVG file to get started'}
              </p>
            )}
            {svgViewBox && origViewBoxRef.current && (
              <div className="zoom-hud" onMouseDown={(e) => e.stopPropagation()}>
                <span>{Math.round(origViewBoxRef.current.vw / svgViewBox.vw * 100)}%</span>
                {Math.abs(svgViewBox.vw - origViewBoxRef.current.vw) > 0.01 && (
                  <button className="zoom-reset-btn" onClick={resetZoom}>Reset</button>
                )}
              </div>
            )}
            {isProcessing && <div className="frame-overlay">Updating…</div>}
          </div>
        </div>

        {/* Corners table */}
        <div className="table-area">
          <div className="table-header">
            <h2>Detected Corners</h2>
            {stats && (
              <div className="summary">
                <span>{stats.cornerCount} found</span>
              </div>
            )}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Path</th>
                  <th>Node</th>
                  <th>X</th>
                  <th>Y</th>
                  <th>Angle °</th>
                  <th>Prev Len</th>
                  <th>Next Len</th>
                  {workflow === 'preview_arcs' && <th>Radius</th>}
                </tr>
              </thead>
              <tbody>
                {corners.length === 0 ? (
                  <tr className="empty-row">
                    <td colSpan={workflow === 'preview_arcs' ? 8 : 7}>No corners detected yet</td>
                  </tr>
                ) : (
                  corners.map((corner, index) => {
                    const key = `${corner.path_id}:${corner.node_id}`
                    const overrideVal = cornerRadiusOverrides[key]
                    return (
                      <tr key={`${corner.path_id}-${corner.node_id}-${index}`}>
                        <td>{corner.path_id}</td>
                        <td>{corner.node_id}</td>
                        <td>{corner.x}</td>
                        <td>{corner.y}</td>
                        <td>{corner.angle_deg}</td>
                        <td>{corner.prev_segment_length}</td>
                        <td>{corner.next_segment_length}</td>
                        {workflow === 'preview_arcs' && (
                          <td>
                            <input
                              className="radius-override-input"
                              type="number"
                              min="0.5"
                              max="120"
                              step="0.5"
                              placeholder={normalizedParams.cornerRadius}
                              value={overrideVal ?? ''}
                              onChange={(e) => {
                                const val = e.target.value === '' ? undefined : Number(e.target.value)
                                setCornerRadiusOverrides((prev) => {
                                  const next = { ...prev }
                                  if (val === undefined) {
                                    delete next[key]
                                  } else {
                                    next[key] = val
                                  }
                                  return next
                                })
                              }}
                            />
                          </td>
                        )}
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>
  )
}

export default App
