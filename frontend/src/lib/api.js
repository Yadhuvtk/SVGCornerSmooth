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

  const response = await fetch(endpoint(path), {
    method: 'POST',
    body: form,
    signal,
  })

  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload?.ok === false) {
    const message = payload?.error || `Request failed (${response.status})`
    throw new Error(message)
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

export async function fetchProfiles(signal) {
  const response = await fetch(endpoint('/api/profiles'), { signal })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.error || 'Failed to load profiles')
  }
  return payload
}
