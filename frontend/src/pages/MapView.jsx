import { useState } from 'react'

export default function MapView() {
  const [campus, setCampus] = useState("sfu")
  const [score, setScore] = useState(null)

  // FE builds the map layout here (MapContainer, SearchBar, CampusPicker, ScorePanel)
  return (
    <div className="flex h-screen bg-black">
      <div className="flex-1 flex items-center justify-center text-white">
        <p className="text-2xl font-serif">Headway — Coming Soon</p>
      </div>
    </div>
  )
}
