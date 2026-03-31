import { useMemo, useState } from 'react'
import './App.css'
import ControlsPanel from './components/ControlsPanel'
import CornerTable from './components/CornerTable'
import DiagnosticsPanel from './components/DiagnosticsPanel'
import PreviewPane from './components/PreviewPane'
import Toolbar from './components/Toolbar'
import UploadPanel from './components/UploadPanel'
import { useSvgProcessor } from './hooks/useSvgProcessor'
import { sanitizeSvg } from './lib/svgViewBox'

export default function App() {
  const {
    inputFile,
    originalSvgText,
    processedSvgText,
    corners,
    summary,
    diagnostics,
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
  } = useSvgProcessor()

  const [showInputViewer, setShowInputViewer] = useState(false)

  const previewResetToken = inputFile ? `${inputFile.name}:${inputFile.lastModified}` : 'none'
  const inputViewerMarkup = useMemo(() => sanitizeSvg(originalSvgText), [originalSvgText])

  return (
    <div className="app-shell">
      <Toolbar loading={loading} activeAction={activeAction} summary={summary} />

      <div className="app-body">
        <aside className="sidebar">
          <UploadPanel inputFile={inputFile} onFileSelect={selectFile} />
          <ControlsPanel
            params={params}
            overlays={overlays}
            profiles={profiles}
            loading={loading}
            activeAction={activeAction}
            hasFile={Boolean(inputFile)}
            onParam={setParam}
            onOverlay={setOverlay}
            onAnalyze={() => runAction('analyze')}
            onPreview={() => runAction('preview')}
            onRound={() => runAction('round')}
            onDownloadSvg={downloadProcessedSvg}
            onDownloadDiagnostics={downloadDiagnostics}
          />
          <DiagnosticsPanel summary={summary} diagnostics={diagnostics} error={error} loading={loading} />
        </aside>

        <main className="main-panel">
          <div className="processed-head">
            <h2>Processed Output</h2>
            <div className="processed-head-actions">
              <button
                className="ghost-btn"
                disabled={!originalSvgText}
                onClick={() => setShowInputViewer(true)}
              >
                View Input
              </button>
            </div>
          </div>

          <PreviewPane
            title="Processed"
            svgText={processedSvgText}
            selectedCorner={selectedCorner}
            showHighlight
            loading={loading}
            loadingMode={activeAction}
            resetToken={previewResetToken}
          />

          <CornerTable
            corners={corners}
            selectedCornerKey={selectedCornerKey}
            onSelectCorner={setSelectedCornerKey}
            cornerOverrides={cornerOverrides}
            onOverrideRadius={setCornerRadiusOverride}
          />
        </main>
      </div>

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
