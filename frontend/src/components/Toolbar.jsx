export default function Toolbar({ loading, activeAction, summary }) {
  const modeLabel =
    activeAction === 'round'
      ? 'Rounded output'
      : activeAction === 'preview'
        ? 'Arc preview'
        : 'Corner analysis'

  return (
    <header className="toolbar">
      <div>
        <h1>SVG Corner Smooth</h1>
        <p>Production-style corner detection and safe fillet rounding</p>
      </div>
      <div className="toolbar-right">
        <span className={`status-pill ${loading ? 'is-loading' : ''}`}>{loading ? 'Processing...' : 'Idle'}</span>
        <span className="mode-pill">{modeLabel}</span>
        <span className="summary-pill">
          corners: {summary?.corners_found ?? 0} | rounded: {summary?.corners_rounded ?? 0}
        </span>
      </div>
    </header>
  )
}
