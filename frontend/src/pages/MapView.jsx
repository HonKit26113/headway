import { useState, useRef } from 'react'
import MapContainer from '../components/MapContainer'
import ScorePanel from '../components/ScorePanel'
import Legend from '../components/Legend'
import SearchBar from '../components/SearchBar'
import CampusPicker from '../components/CampusPicker'
import RouteLegend from '../components/RouteLegend'

export default function MapView() {
  const [campus, setCampus] = useState('sfu')
  const [result, setResult] = useState(null)
  const [pin, setPin] = useState(null)
  const [heatmapEnabled, setHeatmapEnabled] = useState(false)
  const [stopsEnabled, setStopsEnabled] = useState(true)
  const [loading, setLoading] = useState(false)
  const [summaryLoading, setSummaryLoading] = useState(false)
  const searchBarRef = useRef(null)

  return (
    <div className="flex h-screen bg-black">
      <div className="flex-1 relative">
        <MapContainer
          campus={campus}
          pin={pin}
          heatmapEnabled={heatmapEnabled}
          stopsEnabled={stopsEnabled}
          onStopClick={(stop) => searchBarRef.current?.selectLocation(stop)}
        />
        <SearchBar
          ref={searchBarRef}
          campus={campus}
          onResult={setResult}
          onLocationSelect={setPin}
          onLoadingChange={setLoading}
          onSummaryLoadingChange={setSummaryLoading}
        />
        <CampusPicker campus={campus} onChange={setCampus} />
        <RouteLegend />
        <div className="absolute bottom-6 left-6 z-10 flex items-center gap-4">
          <Legend />
          
          <div className="flex gap-2">
            <button
              onClick={() => setStopsEnabled(!stopsEnabled)}
              className="px-5 py-2.5 rounded-full font-medium transition-colors h-fit"
              style={{
                background: stopsEnabled ? '#FF5A2E' : 'rgba(11,11,12,0.92)',
                color: stopsEnabled ? '#000' : '#fff',
                border: stopsEnabled ? '1px solid #FF5A2E' : '1px solid #2a2a2e'
              }}
            >
              {stopsEnabled ? 'Stops: ON' : 'Stops: OFF'}
            </button>
            <button
              onClick={() => setHeatmapEnabled(!heatmapEnabled)}
              className="px-5 py-2.5 rounded-full font-medium transition-colors h-fit"
              style={{
                background: heatmapEnabled ? '#FF5A2E' : 'rgba(11,11,12,0.92)',
                color: heatmapEnabled ? '#000' : '#fff',
                border: heatmapEnabled ? '1px solid #FF5A2E' : '1px solid #2a2a2e'
              }}
            >
              {heatmapEnabled ? 'Heatmap: ON' : 'Heatmap: OFF'}
            </button>
          </div>
        </div>
      </div>
      <ScorePanel result={result} isSample={!result} loading={summaryLoading} />
    </div>
  )
}
