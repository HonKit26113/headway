const NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'

export async function searchAddress(query) {
  if (!query || query.trim().length < 3) return []

  const params = new URLSearchParams({
    q: query,
    format: 'json',
    addressdetails: '1',
    countrycodes: 'ca',
    limit: '5',
  })

  const res = await fetch(`${NOMINATIM_URL}?${params}`)
  if (!res.ok) return []

  const data = await res.json()
  return data.map((item) => ({
    id: item.place_id,
    label: item.display_name,
    lat: parseFloat(item.lat),
    lon: parseFloat(item.lon),
  }))
}
