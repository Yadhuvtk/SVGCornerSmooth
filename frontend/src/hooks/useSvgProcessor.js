import { useCallback, useEffect, useRef, useState } from 'react'
import { analyzeSvg, fetchHealth, fetchProfiles, processSvgCompat, roundSvg } from '../lib/api'

const EXPECTED_API_REVISION = 3
const OUTDATED_BACKEND_WARNING = 'Backend looks outdated. Restart backend to use latest corner detection.'

const FINALIZE_PARAMS = Object.freeze({
  angleThreshold: 45,
  samplesPerCurve: 25,
  markerRadius: 3,
  minSegmentLength: 1,
  cornerRadius: 12,
  detectionMode: 'strict_junction',
  radiusProfile: 'adaptive',
  maxRadiusShrinkIterations: 10,
  minAllowedRadius: 0.5,
  intersectionSafetyMargin: 0.01,
  skipInvalidCorners: true,
  exactCurveTrim: true,
  debug: false,
})

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
  const [activeAction, setActiveAction] = useState('')
  const [showAnalyzeDelayMessage, setShowAnalyzeDelayMessage] = useState(false)
  const [error, setError] = useState('')
  const [backendRevisionWarning, setBackendRevisionWarning] = useState('')
  const [fatalError, setFatalError] = useState(null)

  const abortRef = useRef(null)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([fetchProfiles(controller.signal), fetchHealth(controller.signal)])
      .then(([profilesPayload, healthPayload]) => {
        if (controller.signal.aborted) return
        setError('')
        setFatalError(null)
        const resolvedRevision = Number(profilesPayload?.api_revision ?? healthPayload?.api_revision)
        if (!Number.isFinite(resolvedRevision) || resolvedRevision < EXPECTED_API_REVISION) {
          setBackendRevisionWarning(OUTDATED_BACKEND_WARNING)
        } else {
          setBackendRevisionWarning('')
        }
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : 'Failed to connect backend.')
        setBackendRevisionWarning('')
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

  const withRequestState = useCallback(async (actionName, runner) => {
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
    setActiveAction(actionName)
    setError('')
    setShowAnalyzeDelayMessage(false)

    const shouldShowAnalyzeDelay = actionName === 'finalize' || actionName === 'legacy-analyze'
    const analyzeDelayTimer = shouldShowAnalyzeDelay
      ? setTimeout(() => {
          if (!controller.signal.aborted) {
            setShowAnalyzeDelayMessage(true)
          }
        }, 2000)
      : null

    try {
      await runner(controller.signal)
    } catch (err) {
      if (controller.signal.aborted) return
      setError(err instanceof Error ? err.message : 'Failed to process SVG.')
      if (isBackendOfflineError(err)) {
        setFatalError(new Error('backend_offline'))
      }
      setPipelineStage('idle')
    } finally {
      if (analyzeDelayTimer) {
        clearTimeout(analyzeDelayTimer)
      }
      setShowAnalyzeDelayMessage(false)
      if (!controller.signal.aborted) {
        setLoading(false)
        setActiveAction('')
      }
    }
  }, [inputFile])

  const runFinalizePipeline = useCallback(async () => {
    await withRequestState('finalize', async (signal) => {
      setPipelineStage('analyze')
      const analyzePayload = await analyzeSvg({
        file: inputFile,
        params: requestParamsForMode('analyze'),
        signal,
      })
      if (signal.aborted) return
      applyPayload(analyzePayload)

      setPipelineStage('preview')
      const previewPayload = await processSvgCompat({
        file: inputFile,
        params: requestParamsForMode('preview'),
        signal,
      })
      if (signal.aborted) return
      applyPayload(previewPayload)

      setPipelineStage('round')
      const roundedPayload = await roundSvg({
        file: inputFile,
        params: {
          ...requestParamsForMode('round'),
          cornerRadiusOverridesJson:
            Object.keys(cornerOverrides).length > 0 ? JSON.stringify(cornerOverrides) : undefined,
        },
        signal,
      })
      if (signal.aborted) return
      applyPayload(roundedPayload)
      // Keep final geometry exactly as backend produced it.
      // Additional client-side path conversion can alter sensitive glyph contours.
      setProcessedSvgText(getSvgText(roundedPayload))
      setPipelineStage('done')
    })
  }, [applyPayload, cornerOverrides, inputFile, withRequestState])

  const runLegacyAnalyze = useCallback(async () => {
    await withRequestState('legacy-analyze', async (signal) => {
      setPipelineStage('analyze')
      const payload = await analyzeSvg({
        file: inputFile,
        params: requestParamsForMode('analyze'),
        signal,
      })
      if (signal.aborted) return
      applyPayload(payload)
      setProcessedSvgText(getSvgText(payload))
      setPipelineStage('done')
    })
  }, [applyPayload, inputFile, withRequestState])

  const runLegacyPreview = useCallback(async () => {
    await withRequestState('legacy-preview', async (signal) => {
      setPipelineStage('preview')
      const payload = await processSvgCompat({
        file: inputFile,
        params: requestParamsForMode('preview'),
        signal,
      })
      if (signal.aborted) return
      applyPayload(payload)
      setProcessedSvgText(getSvgText(payload))
      setPipelineStage('done')
    })
  }, [applyPayload, inputFile, withRequestState])

  const runLegacyRound = useCallback(async () => {
    await withRequestState('legacy-round', async (signal) => {
      setPipelineStage('round')
      const payload = await roundSvg({
        file: inputFile,
        params: {
          ...requestParamsForMode('round'),
          cornerRadiusOverridesJson:
            Object.keys(cornerOverrides).length > 0 ? JSON.stringify(cornerOverrides) : undefined,
        },
        signal,
      })
      if (signal.aborted) return
      applyPayload(payload)
      setProcessedSvgText(getSvgText(payload))
      setPipelineStage('done')
    })
  }, [applyPayload, cornerOverrides, inputFile, withRequestState])

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
    activeAction,
    showAnalyzeDelayMessage,
    error,
    backendRevisionWarning,
    fatalError,
    cornerOverrides,
    selectFile,
    runFinalizePipeline,
    runLegacyAnalyze,
    runLegacyPreview,
    runLegacyRound,
    downloadProcessedSvg,
    updateCornerOverride,
    resetCornerOverride,
    resetAllOverrides,
    loadingMode: normalizeStage(pipelineStage),
  }
}
