const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export class ScoreApiError extends Error {
  constructor(status, detail) {
    super(detail || `Score request failed: ${status}`)
    this.status = status
  }
}

export async function fetchScore(address, campus) {
  const res = await fetch(`${API_URL}/api/score`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address, campus }),
  })

  if (!res.ok) {
    let detail = null
    try {
      detail = (await res.json()).detail
    } catch {
      // response wasn't JSON - fall back to the generic message
    }
    throw new ScoreApiError(res.status, detail)
  }

  return res.json()
}

export async function fetchSummary(score, factors, campus) {
  try {
    const res = await fetch(`${API_URL}/api/summary`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ score, factors, campus }),
    })
    if (!res.ok) return null
    const data = await res.json()
    return data.summary ?? null
  } catch {
    return null // the verdict sentence is a nice-to-have - never let it break the score
  }
}
