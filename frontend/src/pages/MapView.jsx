import { useState } from 'react'
import MapContainer from '../components/MapContainer'
import ScorePanel from '../components/ScorePanel'
import Legend from '../components/Legend'

export default function MapView() {
  const [campus, setCampus] = useState('sfu')

  // FE still needs: SearchBar, CampusPicker, and wiring ScorePanel to real /api/score
  return (
    <div className="flex h-screen bg-black">
      <div className="flex-1 relative">
        <MapContainer campus={campus} />
        <Legend />
      </div>
      <ScorePanel />
    </div>
  )
}
