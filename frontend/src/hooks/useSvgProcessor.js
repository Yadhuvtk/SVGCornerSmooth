import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { analyzeSvg, fetchProfiles, processSvgCompat, roundSvg } from '../lib/api'
import { optimizeSvg } from '../lib/svgoOptimize'

const FINALIZE_PARAMS = Object.freeze({
  angleThreshold: 45,
  samplesPerCurve: 25,
  markerRadius: 3,
  minSegmentLength: 1,
  cornerRadius: 12,
  detectionMode: 'accurate',
  radiusProfile: 'adaptive',
  maxRadiusShrinkIterations: 10,
  minAllowedRadius: 0.5,
  intersectionSafetyMargin: 0.01,
  skipInvalidCorners: true,
  exactCurveTrim: true,
  debug: false,
})

const STAGE_PROGRESS = {
  idle: 0,
  analyze: 0.18,
  preview: 0.62,
  round: 0.9,
  done: 1,
}

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Failed to read SVG file'))
    reader.onload = () => resolve(String(reader.result || ''))
    reader.readAsText(file)
  })
}

function requestParamsForMode(mode) {
  return {
    ...FINALIZE_PARAMS,
    applyRounding: mode === 'round',
    previewArcs: mode === 'preview',
    exportMode: mode === 'round' ? 'apply_rounding' : mode === 'preview' ? 'preview_arcs' : 'markers_only',
  }
}

function getSvgText(payload) {
  return payload?.svg || payload?.processedSvg || ''
}

function normalizeStage(stage) {
  return stage === 'idle' ? 'analyze' : stage
}

function isBackendOfflineError(err) {
  const message = err instanceof Error ? err.message : String(err || '')
  return message.includes('Cannot reach SVGCornerSmooth backend')
}

export function useSvgProcessor() {
  const [inputFile, setInputFile] = useState(null)
  const [originalSvgText, setOriginalSvgText] = useState('')
  const [processedSvgText, setProcessedSvgText] = useState('')
  const [summary, setSummary] = useState(null)
  const [diagnostics, setDiagnostics] = useState(null)
  const [corners, setCorners] = useState([])
  const [cornerOverrides, setCornerOverrides] = useState({})
  const [arcPreview, setArcPreview] = useState([])
  const [pipelineStage, setPipelineStage] = useState('idle')
  const [loading, setLoading] = useState(false)
  const [showAnalyzeDelayMessage, setShowAnalyzeDelayMessage] = useState(false)
  const [error, setError] = useState('')
  const [fatalError, setFatalError] = useState(null)

  const abortRef = useRef(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchProfiles(controller.signal)
      .then(() => {
        if (controller.signal.aborted) return
        setError('')
        setFatalError(null)
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : 'Failed to connect backend.')
        if (isBackendOfflineError(err)) {
          setFatalError(new Error('backend_offline'))
        }
      })
    return () => {
      controller.abort()
      if (abortRef.current) {
        abortRef.current.abort()
      }
    }
  }, [])

  const selectFile = useCallback(async (file) => {
    setError('')
    setProcessedSvgText('')
    setSummary(null)
    setDiagnostics(null)
    setCorners([])
    setCornerOverrides({})
    setArcPreview([])
    setPipelineStage('idle')
    setShowAnalyzeDelayMessage(false)

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

  const applyPayload = useCallback((payload) => {
    setSummary(payload?.summary || null)
    setDiagnostics(payload?.diagnostics || null)
    setCorners(payload?.corners || [])
    setArcPreview(payload?.arc_preview || payload?.arcCircles || [])
  }, [])

  const runFinalizePipeline = useCallback(async () => {
    if (!inputFile) {
      setError('Please upload an SVG first.')
      return
    }

    if (abortRef.current) {
      abortRef.current.abort()
    }
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError('')
    setShowAnalyzeDelayMessage(false)
    const analyzeDelayTimer = setTimeout(() => {
      if (!controller.signal.aborted) {
        setShowAnalyzeDelayMessage(true)
      }
    }, 2000)

    try {
      setPipelineStage('analyze')
      const analyzePayload = await analyzeSvg({
        file: inputFile,
        params: requestParamsForMode('analyze'),
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      clearTimeout(analyzeDelayTimer)
      setShowAnalyzeDelayMessage(false)
      applyPayload(analyzePayload)

      setPipelineStage('preview')
      const previewPayload = await processSvgCompat({
        file: inputFile,
        params: requestParamsForMode('preview'),
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      applyPayload(previewPayload)
      setProcessedSvgText(getSvgText(previewPayload))

      setPipelineStage('round')
      const roundedPayload = await roundSvg({
        file: inputFile,
        params: {
          ...requestParamsForMode('round'),
          cornerRadiusOverridesJson:
            Object.keys(cornerOverrides).length > 0 ? JSON.stringify(cornerOverrides) : undefined,
        },
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      applyPayload(roundedPayload)
      setProcessedSvgText(optimizeSvg(getSvgText(roundedPayload)))
      setPipelineStage('done')
    } catch (err) {
      if (controller.signal.aborted) return
      clearTimeout(analyzeDelayTimer)
      setShowAnalyzeDelayMessage(false)
      setError(err instanceof Error ? err.message : 'Failed to process SVG.')
      if (isBackendOfflineError(err)) {
        setFatalError(new Error('backend_offline'))
      }
      setPipelineStage('idle')
    } finally {
      clearTimeout(analyzeDelayTimer)
      setShowAnalyzeDelayMessage(false)
      if (!controller.signal.aborted) {
        setLoading(false)
      }
    }
  }, [applyPayload, cornerOverrides, inputFile])

  const updateCornerOverride = useCallback((key, rawValue) => {
    const text = String(rawValue ?? '').trim()
    if (!text) {
      setCornerOverrides((prev) => {
        if (!(key in prev)) return prev
        const next = { ...prev }
        delete next[key]
        return next
      })
      return
    }

    const radius = Number(text)
    if (!Number.isFinite(radius) || radius <= 0) {
      return
    }
    setCornerOverrides((prev) => ({ ...prev, [key]: radius }))
  }, [])

  const resetCornerOverride = useCallback((key) => {
    setCornerOverrides((prev) => {
      if (!(key in prev)) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }, [])

  const resetAllOverrides = useCallback(() => {
    setCornerOverrides({})
  }, [])

  const downloadProcessedSvg = useCallback(() => {
    if (!processedSvgText) return
    const blob = new Blob([processedSvgText], { type: 'image/svg+xml;charset=utf-8' })
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = 'finalized.svg'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(href)
  }, [processedSvgText])

  const stageProgress = useMemo(() => STAGE_PROGRESS[pipelineStage] ?? 0, [pipelineStage])

  return {
    inputFile,
    originalSvgText,
    processedSvgText,
    summary,
    diagnostics,
    corners,
    arcPreview,
    pipelineStage,
    loading,
    showAnalyzeDelayMessage,
    error,
    fatalError,
    stageProgress,
    cornerOverrides,
    selectFile,
    runFinalizePipeline,
    downloadProcessedSvg,
    updateCornerOverride,
    resetCornerOverride,
    resetAllOverrides,
    loadingMode: normalizeStage(pipelineStage),
  }
}
