const API_BASE = import.meta.env.VITE_API_BASE || ''

function endpoint(path) {
  if (!API_BASE) return path
  return `${API_BASE}${path}`
}

async function sendSvgRequest(path, { file, params, signal }) {
  const form = new FormData()
  form.append('file', file)

  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null) return
    form.append(key, String(value))
  })

  let response
  try {
    response = await fetch(endpoint(path), {
      method: 'POST',
      body: form,
      signal,
    })
  } catch {
    throw new Error('Cannot reach SVGCornerSmooth backend. Start `python api_server.py` (default: 127.0.0.1:5050).')
  }

  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload?.ok === false) {
    const message = payload?.error || `Request failed (${response.status})`
    throw new Error(message)
  }
  if (payload?.diagnostics?.source === 'svg_passthrough') {
    throw new Error('Connected API is not SVGCornerSmooth backend. Start this project backend on 127.0.0.1:5050.')
  }
  return payload
}

export function analyzeSvg({ file, params, signal }) {
  return sendSvgRequest('/api/analyze', { file, params, signal })
}

export function roundSvg({ file, params, signal }) {
  return sendSvgRequest('/api/round', { file, params, signal })
}

export function processSvgCompat({ file, params, signal }) {
  return sendSvgRequest('/api/process', { file, params, signal })
}

export async function fetchHealth(signal) {
  let response
  try {
    response = await fetch(endpoint('/api/health'), { signal })
  } catch {
    throw new Error('Cannot reach SVGCornerSmooth backend. Start `python api_server.py` (default: 127.0.0.1:5050).')
  }
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.error || 'Failed to load health')
  }
  return payload
}

export async function fetchProfiles(signal) {
  let response
  try {
    response = await fetch(endpoint('/api/profiles'), { signal })
  } catch {
    throw new Error('Cannot reach SVGCornerSmooth backend. Start `python api_server.py` (default: 127.0.0.1:5050).')
  }
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.error || 'Failed to load profiles')
  }
  const hasExpectedSchema = Array.isArray(payload?.detection_modes) && Array.isArray(payload?.radius_profiles)
  if (!hasExpectedSchema) {
    throw new Error('Connected API is not SVGCornerSmooth backend. Start this project backend on 127.0.0.1:5050.')
  }
  return payload
}
