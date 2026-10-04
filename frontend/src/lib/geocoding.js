const NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'

// Mirrors backend/service/geocoding.py's METRO_VAN_BBOX - keep in sync.
const METRO_VAN_BBOX = { latMin: 48.9, latMax: 49.6, lonMin: -123.5, lonMax: -122.2 }

function inBbox(lat, lon) {
  return (
    lat >= METRO_VAN_BBOX.latMin && lat <= METRO_VAN_BBOX.latMax &&
    lon >= METRO_VAN_BBOX.lonMin && lon <= METRO_VAN_BBOX.lonMax
  )
}

export async function searchAddress(query) {
  if (!query || query.trim().length < 3) return []

  const { latMin, latMax, lonMin, lonMax } = METRO_VAN_BBOX
  const params = new URLSearchParams({
    q: query,
    format: 'json',
    addressdetails: '1',
    countrycodes: 'ca',
    limit: '5',
    viewbox: `${lonMin},${latMax},${lonMax},${latMin}`,
    bounded: '1',
  })

  const res = await fetch(`${NOMINATIM_URL}?${params}`)
  if (!res.ok) return []

  const data = await res.json()
  return data
    .map((item) => ({
      id: item.place_id,
      label: item.display_name,
      lat: parseFloat(item.lat),
      lon: parseFloat(item.lon),
    }))
    .filter((item) => inBbox(item.lat, item.lon)) // belt-and-suspenders, same as the backend
}
