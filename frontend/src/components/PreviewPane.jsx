import { useEffect, useMemo, useRef, useState } from 'react'
/* eslint-disable react-hooks/immutability, react-hooks/exhaustive-deps */
import { sanitizeSvg, withCornerHighlight } from '../lib/svgViewBox'

const ZOOM_MIN = 0.08
const ZOOM_MAX = 32
const ZOOM_BUTTON_STEP = 1.1
const ZOOM_WHEEL_SPEED = 0.0015
const ZOOM_WHEEL_MULTIPLIER_MIN = 0.85
const ZOOM_WHEEL_MULTIPLIER_MAX = 1.2
const ZOOM_MIDDLE_DRAG_SPEED = 0.008

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
}

function wheelMultiplierFromDelta(deltaY) {
  const raw = Math.exp(-deltaY * ZOOM_WHEEL_SPEED)
  return clamp(raw, ZOOM_WHEEL_MULTIPLIER_MIN, ZOOM_WHEEL_MULTIPLIER_MAX)
}

function normalizeWheelDelta(deltaY, deltaMode) {
  // Some devices emit wheel values in "lines" or "pages" instead of pixels.
  if (deltaMode === 1) return deltaY * 40
  if (deltaMode === 2) return deltaY * 800
  return deltaY
}

function snapToDevicePixel(value) {
  if (typeof window === 'undefined') return value
  const dpr = window.devicePixelRatio || 1
  return Math.round(value * dpr) / dpr
}

function snapPan(point) {
  return {
    x: snapToDevicePixel(point.x),
    y: snapToDevicePixel(point.y),
  }
}

function modeLabel(mode) {
  if (mode === 'preview') return 'Building arc preview...'
  if (mode === 'round') return 'Finalizing smooth corners...'
  return 'Finding sharp corners...'
}

export default function PreviewPane({
  title,
  svgText,
  selectedCorner,
  loading,
  showHighlight = false,
  loadingMode = 'analyze',
  resetToken = 'default',
}) {
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isMiddleZooming, setIsMiddleZooming] = useState(false)

  const dragRef = useRef(null)
  const middleZoomRef = useRef(null)
  const canvasRef = useRef(null)
  const pointerRef = useRef({ x: 0, y: 0, inside: false })
  const zoomRef = useRef(zoom)
  const panRef = useRef(pan)

  useEffect(() => {
    zoomRef.current = zoom
  }, [zoom])

  useEffect(() => {
    panRef.current = pan
  }, [pan])

  // Reset zoom only when source file changes, not every output refresh.
  useEffect(() => {
    zoomRef.current = 1
    panRef.current = snapPan({ x: 0, y: 0 })
    setZoom(1)
    setPan(snapPan({ x: 0, y: 0 }))
  }, [resetToken])

  useEffect(() => {
    function onMove(event) {
      pointerRef.current = { x: event.clientX, y: event.clientY, inside: true }

      if (middleZoomRef.current) {
        const { startY, startZoom } = middleZoomRef.current
        const deltaY = event.clientY - startY
        const multiplier = Math.exp(-deltaY * ZOOM_MIDDLE_DRAG_SPEED)
        zoomTo(startZoom * multiplier, event.clientX, event.clientY)
        return
      }

      if (!dragRef.current) return
      const { startX, startY, startPan } = dragRef.current
      const nextPan = snapPan({
        x: startPan.x + (event.clientX - startX),
        y: startPan.y + (event.clientY - startY),
      })
      panRef.current = nextPan
      setPan(nextPan)
    }

    function onUp() {
      dragRef.current = null
      middleZoomRef.current = null
      setIsMiddleZooming(false)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  const displaySvg = useMemo(() => {
    if (!svgText) return ''
    if (showHighlight && selectedCorner) {
      return withCornerHighlight(svgText, selectedCorner)
    }
    return sanitizeSvg(svgText)
  }, [svgText, selectedCorner, showHighlight])

  function getCanvasAnchor(anchorClientX, anchorClientY) {
    const canvas = canvasRef.current
    if (!canvas) return null

    const rect = canvas.getBoundingClientRect()
    const clientX = anchorClientX ?? rect.left + rect.width / 2
    const clientY = anchorClientY ?? rect.top + rect.height / 2

    return {
      x: clamp(clientX - rect.left, 0, rect.width),
      y: clamp(clientY - rect.top, 0, rect.height),
    }
  }

  function zoomTo(targetZoom, anchorClientX, anchorClientY) {
    const previousZoom = zoomRef.current
    const nextZoom = clamp(targetZoom, ZOOM_MIN, ZOOM_MAX)
    if (Math.abs(nextZoom - previousZoom) < 1e-9) {
      return
    }

    const anchor = getCanvasAnchor(anchorClientX, anchorClientY)
    let nextPan = panRef.current
    if (anchor) {
      const previousPan = panRef.current
      // Keep the same content point under the cursor while zooming.
      const worldX = (anchor.x - previousPan.x) / previousZoom
      const worldY = (anchor.y - previousPan.y) / previousZoom
      nextPan = snapPan({
        x: anchor.x - worldX * nextZoom,
        y: anchor.y - worldY * nextZoom,
      })
    }

    zoomRef.current = nextZoom
    panRef.current = nextPan
    setZoom(nextZoom)
    setPan(nextPan)
  }

  function zoomUsingPointer(multiplier) {
    const pointer = pointerRef.current
    if (pointer.inside) {
      zoomTo(zoomRef.current * multiplier, pointer.x, pointer.y)
      return
    }
    zoomTo(zoomRef.current * multiplier)
  }

  function onWheel(event) {
    event.preventDefault()
    event.stopPropagation()
    pointerRef.current = { x: event.clientX, y: event.clientY, inside: true }
    const normalizedDelta = normalizeWheelDelta(event.deltaY, event.deltaMode)
    const multiplier = wheelMultiplierFromDelta(normalizedDelta)
    zoomTo(zoomRef.current * multiplier, event.clientX, event.clientY)
  }

  function onMouseMove(event) {
    pointerRef.current = { x: event.clientX, y: event.clientY, inside: true }
  }

  function onMouseLeave() {
    pointerRef.current.inside = false
  }

  function onMouseDown(event) {
    if (event.button === 1) {
      event.preventDefault()
      middleZoomRef.current = {
        startY: event.clientY,
        startZoom: zoomRef.current,
      }
      setIsMiddleZooming(true)
      return
    }

    if (event.button !== 0) return
    dragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      startPan: { ...panRef.current },
    }
  }

  function resetView() {
    const resetPan = snapPan({ x: 0, y: 0 })
    zoomRef.current = 1
    panRef.current = resetPan
    setZoom(1)
    setPan(resetPan)
  }

  return (
    <section className="preview-pane">
      <header>
        <div className="preview-title-row">
          <h3>{title}</h3>
          <div className="preview-badge">zoom: {zoom.toFixed(2)}x</div>
        </div>
        <div className="zoom-controls">
          <button onClick={() => zoomUsingPointer(1 / ZOOM_BUTTON_STEP)}>-</button>
          <input
            type="range"
            min={ZOOM_MIN}
            max={ZOOM_MAX}
            step={0.005}
            value={zoom}
            onChange={(event) => {
              const pointer = pointerRef.current
              if (pointer.inside) {
                zoomTo(Number(event.target.value), pointer.x, pointer.y)
              } else {
                zoomTo(Number(event.target.value))
              }
            }}
          />
          <button onClick={() => zoomUsingPointer(ZOOM_BUTTON_STEP)}>+</button>
          <button onClick={resetView}>Fit</button>
        </div>
      </header>

      <div
        ref={canvasRef}
        className={`preview-canvas ${isMiddleZooming ? 'is-middle-zooming' : ''}`}
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onAuxClick={(event) => {
          if (event.button === 1) {
            event.preventDefault()
          }
        }}
        onMouseMove={onMouseMove}
        onMouseLeave={onMouseLeave}
        onDoubleClick={resetView}
      >
        {!displaySvg ? (
          <div className="preview-empty">No SVG available</div>
        ) : (
          <div
            className={`svg-stage ${loading ? 'is-loading' : ''}`}
            style={{
              transform: `translate(${pan.x}px, ${pan.y}px)`,
              width: `${zoom * 100}%`,
              height: `${zoom * 100}%`,
            }}
            dangerouslySetInnerHTML={{ __html: displaySvg }}
          />
        )}

        {loading ? (
          <div className={`processing-overlay mode-${loadingMode}`}>
            <div className="scan-line" />
            <div className="processing-rings">
              <span />
              <span />
              <span />
            </div>
            <p>{modeLabel(loadingMode)}</p>
          </div>
        ) : null}
      </div>
    </section>
  )
}
