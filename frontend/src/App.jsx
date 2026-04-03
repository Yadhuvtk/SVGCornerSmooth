import { useMemo, useState } from 'react'
import './App.css'
import PreviewPane from './components/PreviewPane'
import { useSvgProcessor } from './hooks/useSvgProcessor'
import { sanitizeSvg } from './lib/svgViewBox'

const STAGE_STATUS_LABELS = {
  idle: 'Upload an SVG and click Finalize SVG',
  analyze: 'Finding sharp corners...',
  preview: 'Building arc preview circles...',
  round: 'Applying final corner rounding...',
  done: 'Optimization complete. Download is ready.',
}

function formatFileSize(bytes) {
  if (!bytes && bytes !== 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

export default function App() {
  const {
    inputFile,
    originalSvgText,
    processedSvgText,
    summary,
    diagnostics,
    corners,
    cornerOverrides,
    loading,
    error,
    backendRevisionWarning,
    fatalError,
    pipelineStage,
    activeAction,
    showAnalyzeDelayMessage,
    selectFile,
    runFinalizePipeline,
    runLegacyAnalyze,
    runLegacyPreview,
    runLegacyRound,
    downloadProcessedSvg,
    updateCornerOverride,
    resetCornerOverride,
    resetAllOverrides,
    loadingMode,
  } = useSvgProcessor()

  const [showInputViewer, setShowInputViewer] = useState(false)
  if (fatalError) {
    throw fatalError
  }

  const inputViewerMarkup = useMemo(() => sanitizeSvg(originalSvgText), [originalSvgText])
  const previewResetToken = inputFile ? `${inputFile.name}:${inputFile.lastModified}` : 'none'
  const previewSvg = processedSvgText || originalSvgText
  const hasOverrides = Object.keys(cornerOverrides).length > 0

  return (
    <div className="app-shell">
      <header className="simple-header">
        <h1>SVG Corner Smooth</h1>
        <p>Simple workflow: choose SVG, finalize, download.</p>
      </header>

      <main className="simple-main">
        <aside className="simple-sidebar">
          <section className="simple-card">
            <h2>Choose SVG</h2>
            <label className="file-input">
              <input
                type="file"
                accept=".svg,image/svg+xml"
                onChange={(event) => selectFile(event.target.files?.[0] || null)}
              />
              <span>Choose SVG File</span>
            </label>
            <div className="file-meta">
              <strong>{inputFile ? inputFile.name : 'No file selected'}</strong>
              <small>{inputFile ? formatFileSize(inputFile.size) : 'Upload an SVG to begin'}</small>
            </div>

            <div className="action-stack">
              <button className="primary-btn" disabled={!inputFile || loading} onClick={runFinalizePipeline}>
                {loading && activeAction === 'finalize' ? STAGE_STATUS_LABELS[pipelineStage] : 'Finalize SVG'}
              </button>
              <button className="ghost-btn" disabled={!processedSvgText || loading} onClick={downloadProcessedSvg}>
                Download SVG
              </button>
              <button className="ghost-btn" disabled={!originalSvgText} onClick={() => setShowInputViewer(true)}>
                View Input
              </button>
            </div>
          </section>

          <section className="simple-card">
            <h2>Legacy</h2>
            <div className="legacy-actions">
              <button
                className="ghost-btn"
                disabled={!inputFile || loading}
                onClick={runLegacyAnalyze}
              >
                {loading && activeAction === 'legacy-analyze' ? 'Finding...' : 'Find Sharp Corners'}
              </button>
              <button
                className="ghost-btn"
                disabled={!inputFile || loading}
                onClick={runLegacyPreview}
              >
                {loading && activeAction === 'legacy-preview' ? 'Previewing...' : 'Add Arc Preview'}
              </button>
              <button
                className="ghost-btn"
                disabled={!inputFile || loading}
                onClick={runLegacyRound}
              >
                {loading && activeAction === 'legacy-round' ? 'Finalizing...' : 'Finalize Round'}
              </button>
            </div>
          </section>

          <section className="simple-card">
            <h2>Status</h2>
            <p className="status-text">{STAGE_STATUS_LABELS[pipelineStage]}</p>
            <div className="mini-stats">
              <div>
                <strong>{summary?.corners_found ?? 0}</strong>
                <span>Corners Found</span>
              </div>
              <div>
                <strong>{summary?.corners_rounded ?? 0}</strong>
                <span>Corners Rounded</span>
              </div>
            </div>

            {diagnostics?.warnings?.length ? (
              <p className="warning-text">{diagnostics.warnings[0]}</p>
            ) : null}
            {backendRevisionWarning ? <p className="warning-text">{backendRevisionWarning}</p> : null}
            {error ? <p className="error-text">{error}</p> : null}
            {loading ? (
              <div className="loading-inline" role="status" aria-live="polite">
                <span className="loading-spinner" />
                <span>Processing SVG...</span>
              </div>
            ) : null}
            {loading && pipelineStage === 'analyze' && showAnalyzeDelayMessage ? (
              <p className="loading-note">Analyzing... this may take a moment for large files</p>
            ) : null}
          </section>

          <section className="simple-card override-card">
            <div className="override-head">
              <h2>Corner Radius Overrides</h2>
              {hasOverrides ? (
                <button className="ghost-btn tiny-btn" onClick={resetAllOverrides}>
                  Reset all overrides
                </button>
              ) : null}
            </div>

            {corners.length === 0 ? (
              <p className="muted-text">Run Finalize SVG once to load detected corners.</p>
            ) : (
              <div className="override-table-wrap">
                <table className="override-table">
                  <thead>
                    <tr>
                      <th>Corner</th>
                      <th>Suggested</th>
                      <th>Override</th>
                      <th>Reset</th>
                    </tr>
                  </thead>
                  <tbody>
                    {corners.map((corner) => {
                      const key = `${corner.path_id}:${corner.node_id}`
                      const hasValue = Object.prototype.hasOwnProperty.call(cornerOverrides, key)
                      return (
                        <tr key={key}>
                          <td>{key}</td>
                          <td>{Number(corner.suggested_radius || 0).toFixed(2)}</td>
                          <td>
                            <input
                              type="number"
                              step="0.1"
                              min="0"
                              value={hasValue ? cornerOverrides[key] : ''}
                              onChange={(event) => updateCornerOverride(key, event.target.value)}
                            />
                          </td>
                          <td>
                            {hasValue ? (
                              <button className="ghost-btn tiny-btn" onClick={() => resetCornerOverride(key)}>
                                Reset
                              </button>
                            ) : null}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </aside>

        <section className="preview-wrap">
          <PreviewPane
            title={processedSvgText ? 'Finalized SVG' : 'SVG Preview'}
            svgText={previewSvg}
            loading={loading}
            loadingMode={loadingMode}
            resetToken={previewResetToken}
          />
        </section>
      </main>

      {showInputViewer ? (
        <div className="input-overlay" onClick={() => setShowInputViewer(false)}>
          <div className="input-overlay-card" onClick={(event) => event.stopPropagation()}>
            <div className="input-overlay-head">
              <h3>Input SVG</h3>
              <button className="ghost-btn" onClick={() => setShowInputViewer(false)}>
                Close
              </button>
            </div>
            <div className="input-overlay-body">
              {inputViewerMarkup ? (
                <div className="input-overlay-stage" dangerouslySetInnerHTML={{ __html: inputViewerMarkup }} />
              ) : (
                <div className="preview-empty">No input SVG loaded.</div>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
