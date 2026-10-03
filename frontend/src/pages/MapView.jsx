import { useState } from 'react'
import MapContainer from '../components/MapContainer'
import ScorePanel from '../components/ScorePanel'
import Legend from '../components/Legend'
import SearchBar from '../components/SearchBar'

export default function MapView() {
  const [campus, setCampus] = useState('sfu')
  const [result, setResult] = useState(null)

  // FE still needs: CampusPicker
  return (
    <div className="flex h-screen bg-black">
      <div className="flex-1 relative">
        <MapContainer campus={campus} />
        <SearchBar campus={campus} onResult={setResult} />
        <Legend />
      </div>
      <ScorePanel result={result} isSample={!result} />
    </div>
  )
}
