function NumberControl({ label, value, min, max, step, onChange }) {
  return (
    <label className="control-row">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  )
}

function buttonClass(base, loading, activeAction, thisAction) {
  if (loading && activeAction === thisAction) {
    return `${base} is-running`
  }
  return base
}

export default function ControlsPanel({
  params,
  overlays,
  profiles,
  loading,
  activeAction,
  hasFile,
  onParam,
  onOverlay,
  onAnalyze,
  onPreview,
  onRound,
  onDownloadSvg,
  onDownloadDiagnostics,
}) {
  const radiusProfiles = profiles?.radius_profiles || ['fixed', 'vectorizer_legacy', 'adaptive', 'preserve_shape', 'aggressive']
  const detectionModes = profiles?.detection_modes || ['fast', 'accurate', 'preserve_shape', 'strict_junction']

  return (
    <section className="panel">
      <h2>Controls</h2>

      <div className="control-grid">
        <NumberControl
          label="Angle Threshold"
          value={params.angleThreshold}
          min={0}
          max={180}
          step={1}
          onChange={(value) => onParam('angleThreshold', value)}
        />
        <NumberControl
          label="Corner Radius"
          value={params.cornerRadius}
          min={0}
          max={200}
          step={0.5}
          onChange={(value) => onParam('cornerRadius', value)}
        />
        <NumberControl
          label="Samples / Curve"
          value={params.samplesPerCurve}
          min={2}
          max={120}
          step={1}
          onChange={(value) => onParam('samplesPerCurve', value)}
        />
        <NumberControl
          label="Marker Radius"
          value={params.markerRadius}
          min={0.5}
          max={40}
          step={0.5}
          onChange={(value) => onParam('markerRadius', value)}
        />
        <NumberControl
          label="Min Segment Length"
          value={params.minSegmentLength}
          min={0}
          max={100}
          step={0.1}
          onChange={(value) => onParam('minSegmentLength', value)}
        />
        <NumberControl
          label="Min Allowed Radius"
          value={params.minAllowedRadius}
          min={0}
          max={50}
          step={0.1}
          onChange={(value) => onParam('minAllowedRadius', value)}
        />
      </div>

      <label className="control-row">
        <span>Detection Mode</span>
        <select value={params.detectionMode} onChange={(event) => onParam('detectionMode', event.target.value)}>
          {detectionModes.map((mode) => (
            <option key={mode} value={mode}>
              {mode}
            </option>
          ))}
        </select>
      </label>

      <label className="control-row">
        <span>Radius Profile</span>
        <select value={params.radiusProfile} onChange={(event) => onParam('radiusProfile', event.target.value)}>
          {radiusProfiles.map((profile) => (
            <option key={profile} value={profile}>
              {profile}
            </option>
          ))}
        </select>
      </label>

      <div className="toggle-grid">
        <label>
          <input type="checkbox" checked={params.livePreview} onChange={(event) => onParam('livePreview', event.target.checked)} />
          Realtime Preview
        </label>
        <label>
          <input type="checkbox" checked={params.debug} onChange={(event) => onParam('debug', event.target.checked)} />
          Debug Labels
        </label>
        <label>
          <input type="checkbox" checked={params.skipInvalidCorners} onChange={(event) => onParam('skipInvalidCorners', event.target.checked)} />
          Skip Invalid Fillets
        </label>
        <label>
          <input type="checkbox" checked={params.exactCurveTrim} onChange={(event) => onParam('exactCurveTrim', event.target.checked)} />
          Exact Curve Trim
        </label>
      </div>

      <div className="toggle-grid">
        <label>
          <input type="checkbox" checked={overlays.cornerMarkers} onChange={(event) => onOverlay('cornerMarkers', event.target.checked)} />
          Corner Markers
        </label>
        <label>
          <input type="checkbox" checked={overlays.angleLabels} onChange={(event) => onOverlay('angleLabels', event.target.checked)} />
          Angle Labels
        </label>
        <label>
          <input type="checkbox" checked={overlays.radiusLabels} onChange={(event) => onOverlay('radiusLabels', event.target.checked)} />
          Radius Labels
        </label>
        <label>
          <input type="checkbox" checked={overlays.rejectedCorners} onChange={(event) => onOverlay('rejectedCorners', event.target.checked)} />
          Rejected Corners
        </label>
      </div>

      <div className="action-grid">
        <button
          className={buttonClass('', loading, activeAction, 'analyze')}
          disabled={!hasFile || loading}
          onClick={onAnalyze}
        >
          {loading && activeAction === 'analyze' ? 'Finding...' : 'Find Sharp Corners'}
        </button>
        <button
          className={buttonClass('', loading, activeAction, 'preview')}
          disabled={!hasFile || loading}
          onClick={onPreview}
        >
          {loading && activeAction === 'preview' ? 'Previewing Arcs...' : 'Add Arc Preview'}
        </button>
        <button
          className={buttonClass('primary', loading, activeAction, 'round')}
          disabled={!hasFile || loading}
          onClick={onRound}
        >
          {loading && activeAction === 'round' ? 'Finalizing...' : 'Finalize Round'}
        </button>
      </div>

      <div className="action-grid">
        <button disabled={loading} onClick={onDownloadSvg}>
          Download SVG
        </button>
        <button disabled={loading} onClick={onDownloadDiagnostics}>
          Export Diagnostics JSON
        </button>
      </div>
    </section>
  )
}
