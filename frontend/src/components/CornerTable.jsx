import { useMemo, useState } from 'react'
import { colorSeverity } from '../lib/colorSeverity'

function sortCorners(corners, sortBy, sortDirection) {
  const factor = sortDirection === 'desc' ? -1 : 1
  return [...corners].sort((a, b) => {
    const av = a[sortBy]
    const bv = b[sortBy]
    if (typeof av === 'number' && typeof bv === 'number') {
      return (av - bv) * factor
    }
    return String(av).localeCompare(String(bv)) * factor
  })
}

export default function CornerTable({
  corners,
  selectedCornerKey,
  onSelectCorner,
  cornerOverrides,
  onOverrideRadius,
}) {
  const [searchText, setSearchText] = useState('')
  const [sortBy, setSortBy] = useState('severity_score')
  const [sortDirection, setSortDirection] = useState('desc')

  const filtered = useMemo(() => {
    const needle = searchText.trim().toLowerCase()
    const base = !needle
      ? corners
      : corners.filter((corner) => {
          const key = `${corner.path_id}:${corner.node_id}`
          return (
            key.includes(needle) ||
            String(corner.join_type || '').toLowerCase().includes(needle) ||
            String(corner.angle_deg).includes(needle)
          )
        })
    return sortCorners(base, sortBy, sortDirection)
  }, [corners, searchText, sortBy, sortDirection])

  function changeSort(next) {
    if (sortBy === next) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
      return
    }
    setSortBy(next)
    setSortDirection(next === 'severity_score' ? 'desc' : 'asc')
  }

  return (
    <section className="corner-table-wrap">
      <header>
        <h3>Detected Corners</h3>
        <div className="corner-tools">
          <input
            type="text"
            placeholder="Search path:node or type"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          <span>{filtered.length} rows</span>
        </div>
      </header>
      <div className="corner-table-scroll">
        <table>
          <thead>
            <tr>
              <th onClick={() => changeSort('path_id')}>path</th>
              <th onClick={() => changeSort('node_id')}>node</th>
              <th onClick={() => changeSort('angle_deg')}>angle</th>
              <th onClick={() => changeSort('severity_score')}>severity</th>
              <th onClick={() => changeSort('suggested_radius')}>radius</th>
              <th>override</th>
              <th onClick={() => changeSort('join_type')}>status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((corner) => {
              const key = `${corner.path_id}:${corner.node_id}`
              const selected = selectedCornerKey === key
              return (
                <tr key={key} className={selected ? 'is-selected' : ''} onClick={() => onSelectCorner(key)}>
                  <td>{corner.path_id}</td>
                  <td>{corner.node_id}</td>
                  <td>{Number(corner.angle_deg).toFixed(2)}</td>
                  <td style={{ color: colorSeverity(Number(corner.severity_score) || 0) }}>
                    {Number(corner.severity_score).toFixed(3)}
                  </td>
                  <td>{Number(corner.suggested_radius || 0).toFixed(2)}</td>
                  <td>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      value={cornerOverrides[key] ?? ''}
                      onChange={(event) => onOverrideRadius(key, event.target.value)}
                      onClick={(event) => event.stopPropagation()}
                    />
                  </td>
                  <td>{corner.join_type || 'corner'}</td>
                </tr>
              )
            })}
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="empty-cell">
                  No corners to display.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  )
}
