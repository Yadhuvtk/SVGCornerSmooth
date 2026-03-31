function formatFileSize(bytes) {
  if (!bytes && bytes !== 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

export default function UploadPanel({ inputFile, onFileSelect }) {
  return (
    <section className="panel">
      <h2>Upload</h2>
      <label className="file-input">
        <input
          type="file"
          accept=".svg,image/svg+xml"
          onChange={(event) => onFileSelect(event.target.files?.[0] || null)}
        />
        <span>Choose SVG File</span>
      </label>
      <div className="file-meta">
        <strong>{inputFile ? inputFile.name : 'No file selected'}</strong>
        <small>{inputFile ? formatFileSize(inputFile.size) : 'Upload an SVG to begin'}</small>
      </div>
    </section>
  )
}
