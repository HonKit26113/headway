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

  return (
    <div className="flex h-screen bg-black">
      <div className="flex-1 relative">
        <MapContainer campus={campus} pin={pin} />
        <SearchBar campus={campus} onResult={setResult} onLocationSelect={setPin} />
        <CampusPicker campus={campus} onChange={setCampus} />
        <Legend />
      </div>
      <ScorePanel result={result} isSample={!result} />
    </div>
  )
}
