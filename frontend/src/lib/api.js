const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export async function fetchScore(address, campus) {
  const res = await fetch(`${API_URL}/api/score`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address, campus }),
  })

  if (!res.ok) {
    throw new Error(`Score request failed: ${res.status}`)
  }

  return res.json()
}
