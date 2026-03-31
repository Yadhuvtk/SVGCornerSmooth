export default function DiagnosticsPanel({ summary, diagnostics, error, loading }) {
  return (
    <section className="panel diagnostics">
      <h2>Diagnostics</h2>
      <div className="stats-grid">
        <div>
          <strong>{summary?.paths_found ?? 0}</strong>
          <span>Paths</span>
        </div>
        <div>
          <strong>{summary?.corners_found ?? 0}</strong>
          <span>Corners</span>
        </div>
        <div>
          <strong>{summary?.corners_rounded ?? 0}</strong>
          <span>Rounded</span>
        </div>
        <div>
          <strong>{summary?.corners_skipped ?? 0}</strong>
          <span>Skipped</span>
        </div>
      </div>
      <p className="processing-time">Processing: {summary?.processing_ms?.toFixed?.(2) ?? '0.00'} ms</p>
      {loading ? <p className="info-text">Processing request...</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
      <div className="warnings-list">
        {(diagnostics?.warnings || []).slice(0, 6).map((warning, index) => (
          <p key={`${warning}-${index}`}>{warning}</p>
        ))}
      </div>
    </section>
  )
}
