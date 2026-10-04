import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { CAMPUS_COORDS } from '../lib/campuses'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Esri's free dark basemap - no API key needed. Matches the dark map
// preview used on the landing page's About section.
const DARK_STYLE = {
  version: 8,
  sources: {
    'dark-tiles': {
      type: 'raster',
      tiles: [
        'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
      ],
      tileSize: 256,
      attribution: 'Esri, HERE, Garmin, FAO, NOAA, USGS',
    },
  },
  layers: [{ id: 'dark-tiles-layer', type: 'raster', source: 'dark-tiles' }],
}

const EMPTY_FC = { type: 'FeatureCollection', features: [] }

export default function MapContainer({ campus = 'sfu', pin = null, heatmapEnabled = false, stopsEnabled = true, onStopClick }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)
  const heatmapCacheRef = useRef({}) // campus -> GeoJSON (cache the data, not just a "loaded" flag)
  const onStopClickRef = useRef(onStopClick)
  onStopClickRef.current = onStopClick
  const [mapReady, setMapReady] = useState(false)

  useEffect(() => {
    const { lat, lon } = CAMPUS_COORDS[campus]

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: DARK_STYLE,
      center: [lon, lat],
      zoom: 12,
    })
    mapRef.current = map

    map.on('load', () => {
      // 1. Existing stops layer
      map.addSource('stops', { type: 'geojson', data: '/stops.geojson' })
      map.addLayer({
        id: 'stops-layer',
        type: 'circle',
        source: 'stops',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 1.5, 15, 5],
          'circle-color': '#FF5A2E',
          'circle-opacity': [
            'step', ['get', 'departures_per_hour'],
            0.1, 2, 0.22, 4, 0.34, 6, 0.46, 10, 0.58,
          ],
        },
      })

      // 2. Heatmap source (empty initially)
      map.addSource('heatmap-source', { type: 'geojson', data: EMPTY_FC })

      // 3. Score grid layer. Colors are computed by the backend
      //    (properties.color), so there is only one color scale to maintain.
      map.addLayer(
        {
          id: 'score-heatmap',
          type: 'fill',
          source: 'heatmap-source',
          layout: { visibility: 'none' }, // Hidden by default
          paint: {
            'fill-color': ['coalesce', ['get', 'color'], '#cccccc'],
            'fill-opacity': 0.65,
            'fill-outline-color': 'rgba(0,0,0,0)', // Seamless edges
          },
        },
        'stops-layer' // Insert BEFORE stops-layer so pins render on top
      )

      // 4. Route from the pin to campus: rides are solid and colored per line,
      //    walks are dashed. Inserted before stops-layer so stop dots stay on top.
      map.addSource('route-source', { type: 'geojson', data: EMPTY_FC })
      map.addLayer(
        {
          id: 'route-ride-casing',
          type: 'line',
          source: 'route-source',
          filter: ['==', ['get', 'type'], 'ride'],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#0b0b0c', 'line-width': 8, 'line-opacity': 0.8 },
        },
        'stops-layer'
      )
      map.addLayer(
        {
          id: 'route-ride',
          type: 'line',
          source: 'route-source',
          filter: ['==', ['get', 'type'], 'ride'],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': ['coalesce', ['get', 'color'], '#ff5a2e'], 'line-width': 4.5 },
        },
        'stops-layer'
      )
      map.addLayer(
        {
          id: 'route-walk',
          type: 'line',
          source: 'route-source',
          filter: ['==', ['get', 'type'], 'walk'],
          paint: {
            'line-color': '#ffffff',
            'line-width': 2.5,
            'line-dasharray': [1.5, 1.5],
          },
        },
        'stops-layer'
      )

      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false })
      map.on('mouseenter', 'stops-layer', (e) => {
        map.getCanvas().style.cursor = 'pointer'
        const feature = e.features[0]
        popup
          .setLngLat(feature.geometry.coordinates)
          .setHTML(`<div style="font-family: Geist, sans-serif; color: rgb(0,0,0); font-size: 13px;">${feature.properties.name}</div>`)
          .addTo(map)
      })
      map.on('mouseleave', 'stops-layer', () => {
        map.getCanvas().style.cursor = ''
        popup.remove()
      })

      map.on('click', 'stops-layer', (e) => {
        const feature = e.features[0]
        const [lon, lat] = feature.geometry.coordinates
        onStopClickRef.current?.({ label: feature.properties.name, lat, lon })
      })

      // Hover a ride segment to see which line it is
      map.on('mouseenter', 'route-ride', (e) => {
        map.getCanvas().style.cursor = 'pointer'
        popup
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-family: Geist, sans-serif; color: rgb(0,0,0); font-size: 13px;">${e.features[0].properties.line}</div>`)
          .addTo(map)
      })
      map.on('mouseleave', 'route-ride', () => {
        map.getCanvas().style.cursor = ''
        popup.remove()
      })

      setMapReady(true) // Layers exist now; effects that depend on them can run
    })

    return () => {
      setMapReady(false)
      map.remove()
    }
  }, []) // Map initializes once

  // Handle stops toggling
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    map.setLayoutProperty('stops-layer', 'visibility', stopsEnabled ? 'visible' : 'none')
  }, [stopsEnabled, mapReady])

  // Handle heatmap toggling & fetching
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    map.setLayoutProperty('score-heatmap', 'visibility', heatmapEnabled ? 'visible' : 'none')
    if (!heatmapEnabled) return

    const source = map.getSource('heatmap-source')
    if (!source) return

    // Cached: swap the data in immediately (also fixes stale data after switching campus)
    const cached = heatmapCacheRef.current[campus]
    if (cached) {
      source.setData(cached)
      return
    }

    // Clear the previous campus's grid while the new one loads
    source.setData(EMPTY_FC)

    let cancelled = false
    fetch(`${API}/api/heatmap?campus=${campus}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data) => {
        heatmapCacheRef.current[campus] = data
        // Ignore the response if the campus or toggle changed while it was in flight
        if (!cancelled) source.setData(data)
      })
      .catch((e) => console.error('Failed to load heatmap:', e))

    return () => {
      cancelled = true
    }
  }, [heatmapEnabled, campus, mapReady])

  // Route from the pin to campus
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const source = map.getSource('route-source')
    if (!source) return

    if (!pin) {
      source.setData(EMPTY_FC)
      return
    }

    let cancelled = false
    fetch(`${API}/api/route?lat=${pin.lat}&lon=${pin.lon}&campus=${campus}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data) => {
        if (cancelled) return
        source.setData(data)

        // Zoom to fit the whole journey
        const bounds = new maplibregl.LngLatBounds()
        data.features.forEach((f) => f.geometry.coordinates.forEach((c) => bounds.extend(c)))
        if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 80, maxZoom: 15 })
      })
      .catch((e) => {
        console.error('Failed to load route:', e)
        if (!cancelled) source.setData(EMPTY_FC)
      })

    return () => {
      cancelled = true
    }
  }, [pin, campus, mapReady])

  useEffect(() => {
    if (!mapRef.current || pin) return
    const { lat, lon } = CAMPUS_COORDS[campus]
    mapRef.current.flyTo({ center: [lon, lat], zoom: 12 })
  }, [campus])

  useEffect(() => {
    if (!mapRef.current || !pin) return

    if (!markerRef.current) {
      const el = document.createElement('div')
      el.style.width = '16px'
      el.style.height = '16px'
      el.style.borderRadius = '50%'
      el.style.background = '#FF5A2E'
      el.style.border = '3px solid #0b0b0c'
      el.style.boxShadow = '0 0 0 2px #FF5A2E'
      markerRef.current = new maplibregl.Marker({ element: el })
    }

    markerRef.current.setLngLat([pin.lon, pin.lat]).addTo(mapRef.current)
    mapRef.current.flyTo({ center: [pin.lon, pin.lat], zoom: 14 })
  }, [pin])

  return <div ref={containerRef} className="w-full h-full" />
}
