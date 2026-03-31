import { useEffect, useMemo, useRef, useState } from 'react'
import { sanitizeSvg, withCornerHighlight } from '../lib/svgViewBox'

const ZOOM_MIN = 0.08
const ZOOM_MAX = 32

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
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

  const dragRef = useRef(null)
  const canvasRef = useRef(null)
  const pointerRef = useRef({ x: 0, y: 0, inside: false })
  const zoomRef = useRef(zoom)

  useEffect(() => {
    zoomRef.current = zoom
  }, [zoom])

  // Reset zoom only when source file changes, not every output refresh.
  useEffect(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }, [resetToken])

  useEffect(() => {
    function onMove(event) {
      if (!dragRef.current) return
      const { startX, startY, startPan } = dragRef.current
      setPan({ x: startPan.x + (event.clientX - startX), y: startPan.y + (event.clientY - startY) })
    }

    function onUp() {
      dragRef.current = null
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
    setZoom((previousZoom) => {
      const nextZoom = clamp(targetZoom, ZOOM_MIN, ZOOM_MAX)
      if (Math.abs(nextZoom - previousZoom) < 1e-9) {
        return previousZoom
      }

      const anchor = getCanvasAnchor(anchorClientX, anchorClientY)
      if (anchor) {
        setPan((previousPan) => {
          // Keep the same content point under the anchor after zoom.
          const worldX = (anchor.x - previousPan.x) / previousZoom
          const worldY = (anchor.y - previousPan.y) / previousZoom
          return {
            x: anchor.x - worldX * nextZoom,
            y: anchor.y - worldY * nextZoom,
          }
        })
      }

      return nextZoom
    })
  }

  function zoomUsingPointer(multiplier) {
    const pointer = pointerRef.current
    if (pointer.inside) {
      zoomTo(zoomRef.current * multiplier, pointer.x, pointer.y)
      return
    }
    zoomTo(zoomRef.current * multiplier)
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    function onNativeWheel(event) {
      event.preventDefault()
      event.stopPropagation()
      pointerRef.current = { x: event.clientX, y: event.clientY, inside: true }
      const multiplier = event.deltaY < 0 ? 1.12 : 1 / 1.12
      zoomTo(zoomRef.current * multiplier, event.clientX, event.clientY)
    }

    canvas.addEventListener('wheel', onNativeWheel, { passive: false })
    return () => {
      canvas.removeEventListener('wheel', onNativeWheel)
    }
  }, [])

  function onMouseMove(event) {
    pointerRef.current = { x: event.clientX, y: event.clientY, inside: true }
  }

  function onMouseLeave() {
    pointerRef.current.inside = false
  }

  function onMouseDown(event) {
    if (event.button !== 0) return
    dragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      startPan: { ...pan },
    }
  }

  function resetView() {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }

  return (
    <section className="preview-pane">
      <header>
        <div className="preview-title-row">
          <h3>{title}</h3>
          <div className="preview-badge">zoom: {zoom.toFixed(2)}x</div>
        </div>
        <div className="zoom-controls">
          <button onClick={() => zoomUsingPointer(1 / 1.2)}>-</button>
          <input
            type="range"
            min={ZOOM_MIN}
            max={ZOOM_MAX}
            step={0.01}
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
          <button onClick={() => zoomUsingPointer(1.2)}>+</button>
          <button onClick={resetView}>Fit</button>
        </div>
      </header>

      <div
        ref={canvasRef}
        className="preview-canvas"
        onWheelCapture={(event) => {
          event.preventDefault()
          event.stopPropagation()
        }}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseLeave={onMouseLeave}
        onDoubleClick={resetView}
      >
        {!displaySvg ? (
          <div className="preview-empty">No SVG available</div>
        ) : (
          <div
            className={`svg-stage ${loading ? 'is-loading' : ''}`}
            style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
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
