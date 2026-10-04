import { useState } from 'react'
import MapContainer from '../components/MapContainer'
import ScorePanel from '../components/ScorePanel'
import Legend from '../components/Legend'
import SearchBar from '../components/SearchBar'
import CampusPicker from '../components/CampusPicker'

export default function MapView() {
  const [campus, setCampus] = useState('sfu')
  const [result, setResult] = useState(null)
  const [pin, setPin] = useState(null)
  const [heatmapEnabled, setHeatmapEnabled] = useState(false)
  const [loading, setLoading] = useState(false)

  return (
    <div className="flex h-screen bg-black">
      <div className="flex-1 relative">
        <MapContainer campus={campus} pin={pin} heatmapEnabled={heatmapEnabled} />
        <SearchBar
          campus={campus}
          onResult={setResult}
          onLocationSelect={setPin}
          onLoadingChange={setLoading}
        />
        <CampusPicker campus={campus} onChange={setCampus} />
        <div className="absolute bottom-6 left-6 z-10 flex items-center gap-4">
          <Legend />
          
          {/* Heatmap Toggle */}
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
      <ScorePanel result={result} isSample={!result} loading={loading} />
    </div>
  )
}
