export function sanitizeSvg(svgText) {
  if (!svgText) return ''
  let text = svgText
    .replace(/<\?xml[^?]*\?>\s*/i, '')
    .replace(/<!DOCTYPE[^>]*>\s*/i, '')

  // Ensure white background for readability.
  if (!/<rect[^>]*id=["']__viewer_bg__["']/i.test(text)) {
    text = text.replace(
      /<svg([^>]*)>/i,
      '<svg$1><rect id="__viewer_bg__" x="-100000" y="-100000" width="200000" height="200000" fill="#ffffff" />',
    )
  }

  return text.replace(/<svg([^>]*)>/i, (_, attrs) => {
    const updated = attrs
      .replace(/\s+width="[^"]*"/gi, '')
      .replace(/\s+height="[^"]*"/gi, '')
    return `<svg${updated} width="100%" height="100%" preserveAspectRatio="xMidYMid meet">`
  })
}

export function withCornerHighlight(svgText, corner, color = '#ffd166') {
  if (!svgText || !corner) return sanitizeSvg(svgText)
  const highlight = `<g id="__corner_highlight__"><circle cx="${corner.x}" cy="${corner.y}" r="7" fill="none" stroke="${color}" stroke-width="1.8" /><circle cx="${corner.x}" cy="${corner.y}" r="2.2" fill="${color}" /></g>`
  return sanitizeSvg(svgText).replace('</svg>', `${highlight}</svg>`)
}
