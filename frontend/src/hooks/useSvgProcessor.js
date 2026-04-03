import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { analyzeSvg, fetchProfiles, processSvgCompat, roundSvg } from '../lib/api'
import { optimizeSvg } from '../lib/svgoOptimize'

const DEFAULT_PARAMS = {
  angleThreshold: 45,
  samplesPerCurve: 25,
  markerRadius: 3,
  minSegmentLength: 1,
  cornerRadius: 12,
  detectionMode: 'accurate',
  radiusProfile: 'adaptive',
  maxRadiusShrinkIterations: 10,
  minAllowedRadius: 0.25,
  intersectionSafetyMargin: 0.01,
  skipInvalidCorners: true,
  exactCurveTrim: true,
  debug: false,
  livePreview: true,
}

const DEFAULT_OVERLAYS = {
  cornerMarkers: true,
  angleLabels: false,
  radiusLabels: false,
  rejectedCorners: true,
}

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Failed to read SVG file'))
    reader.onload = () => resolve(String(reader.result || ''))
    reader.readAsText(file)
  })
}

function buildRequestParams({ params, overlays, cornerOverrides, mode }) {
  const diagnosticsOverlay = overlays.angleLabels || overlays.radiusLabels || overlays.rejectedCorners

  return {
    angleThreshold: params.angleThreshold,
    samplesPerCurve: params.samplesPerCurve,
    markerRadius: params.markerRadius,
    minSegmentLength: params.minSegmentLength,
    cornerRadius: params.cornerRadius,
    radiusProfile: params.radiusProfile,
    detectionMode: params.detectionMode,
    maxRadiusShrinkIterations: params.maxRadiusShrinkIterations,
    minAllowedRadius: params.minAllowedRadius,
    intersectionSafetyMargin: params.intersectionSafetyMargin,
    skipInvalidCorners: params.skipInvalidCorners,
    exactCurveTrim: params.exactCurveTrim,
    debug: params.debug || overlays.angleLabels || overlays.radiusLabels,
    applyRounding: mode === 'round',
    previewArcs: mode === 'preview',
    exportMode:
      mode === 'round'
        ? 'apply_rounding'
        : mode === 'preview'
          ? 'preview_arcs'
          : diagnosticsOverlay
            ? 'diagnostics_overlay'
            : 'markers_only',
    cornerRadiusOverridesJson:
      cornerOverrides && Object.keys(cornerOverrides).length > 0
        ? JSON.stringify(cornerOverrides)
        : undefined,
  }
}

export function useSvgProcessor() {
  const [inputFile, setInputFile] = useState(null)
  const [originalSvgText, setOriginalSvgText] = useState('')
  const [processedSvgText, setProcessedSvgText] = useState('')
  const [corners, setCorners] = useState([])
  const [summary, setSummary] = useState(null)
  const [diagnostics, setDiagnostics] = useState(null)
  const [arcPreview, setArcPreview] = useState([])
  const [params, setParams] = useState(DEFAULT_PARAMS)
  const [overlays, setOverlays] = useState(DEFAULT_OVERLAYS)
  const [cornerOverrides, setCornerOverrides] = useState({})
  const [selectedCornerKey, setSelectedCornerKey] = useState('')
  const [profiles, setProfiles] = useState(null)
  const [activeAction, setActiveAction] = useState('analyze')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const abortRef = useRef(null)
  const debounceRef = useRef(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchProfiles(controller.signal)
      .then((payload) => setProfiles(payload))
      .catch(() => undefined)
    return () => controller.abort()
  }, [])

  const selectFile = useCallback(async (file) => {
    setError('')
    setProcessedSvgText('')
    setCorners([])
    setSummary(null)
    setDiagnostics(null)
    setArcPreview([])
    setCornerOverrides({})
    setSelectedCornerKey('')

    if (!file) {
      setInputFile(null)
      setOriginalSvgText('')
      return
    }

    if (!file.name.toLowerCase().endsWith('.svg')) {
      setError('Please upload an SVG file.')
      setInputFile(null)
      setOriginalSvgText('')
      return
    }

    const text = await readFileAsText(file)
    setInputFile(file)
    setOriginalSvgText(text)
  }, [])

  const setParam = useCallback((name, value) => {
    setParams((prev) => ({ ...prev, [name]: value }))
  }, [])

  const setOverlay = useCallback((name, value) => {
    setOverlays((prev) => ({ ...prev, [name]: value }))
  }, [])

  const setCornerRadiusOverride = useCallback((cornerKey, radius) => {
    setCornerOverrides((prev) => {
      const next = { ...prev }
      if (!radius || Number(radius) <= 0) {
        delete next[cornerKey]
      } else {
        next[cornerKey] = Number(radius)
      }
      return next
    })
  }, [])

  const runAction = useCallback(
    async (mode, { silent = false } = {}) => {
      if (!inputFile) {
        setError('Please upload an SVG first.')
        return
      }

      setActiveAction(mode)
      setError('')
      setLoading(true)

      if (abortRef.current) {
        abortRef.current.abort()
      }
      const controller = new AbortController()
      abortRef.current = controller

      const requestParams = buildRequestParams({
        params,
        overlays,
        cornerOverrides,
        mode,
      })

      try {
        const payload =
          mode === 'round'
            ? await roundSvg({ file: inputFile, params: requestParams, signal: controller.signal })
            : mode === 'preview'
              ? await processSvgCompat({ file: inputFile, params: requestParams, signal: controller.signal })
              : await analyzeSvg({ file: inputFile, params: requestParams, signal: controller.signal })

        const rawSvg = payload.svg || payload.processedSvg || ''
        setProcessedSvgText(mode === 'round' ? optimizeSvg(rawSvg) : rawSvg)
        setCorners(payload.corners || [])
        setSummary(payload.summary || null)
        setDiagnostics(payload.diagnostics || null)
        setArcPreview(payload.arc_preview || payload.arcCircles || [])
      } catch (err) {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : 'Failed to process SVG.')
        if (!silent) {
          setProcessedSvgText('')
          setCorners([])
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    },
    [inputFile, params, overlays, cornerOverrides],
  )

  useEffect(() => {
    if (!inputFile || !params.livePreview) return

    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current)
    }

    debounceRef.current = window.setTimeout(() => {
      runAction(activeAction, { silent: true })
    }, 320)

    return () => {
      if (debounceRef.current) {
        window.clearTimeout(debounceRef.current)
      }
    }
  }, [inputFile, params, overlays, cornerOverrides, activeAction, runAction])

  const selectedCorner = useMemo(() => {
    if (!selectedCornerKey) return null
    return corners.find((corner) => `${corner.path_id}:${corner.node_id}` === selectedCornerKey) || null
  }, [corners, selectedCornerKey])

  const downloadProcessedSvg = useCallback(() => {
    if (!processedSvgText) return
    const blob = new Blob([processedSvgText], { type: 'image/svg+xml;charset=utf-8' })
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = activeAction === 'round' ? 'rounded.svg' : 'analyzed.svg'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(href)
  }, [processedSvgText, activeAction])

  const downloadDiagnostics = useCallback(() => {
    const payload = {
      summary,
      diagnostics,
      corners,
      arc_preview: arcPreview,
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = 'svg-corner-diagnostics.json'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(href)
  }, [summary, diagnostics, corners, arcPreview])

  return {
    inputFile,
    originalSvgText,
    processedSvgText,
    corners,
    summary,
    diagnostics,
    arcPreview,
    params,
    overlays,
    profiles,
    loading,
    error,
    activeAction,
    selectedCornerKey,
    selectedCorner,
    cornerOverrides,
    selectFile,
    setParam,
    setOverlay,
    setCornerRadiusOverride,
    setSelectedCornerKey,
    runAction,
    downloadProcessedSvg,
    downloadDiagnostics,
  }
}
