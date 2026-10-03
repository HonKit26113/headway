import { useState, useEffect } from 'react'

export default function App() {
  const [campus, setCampus] = useState("sfu")
  const [score, setScore] = useState(null)
  
  // FE builds the layout here
  
  return (
    <div className="flex h-screen bg-black">
      {/* FE components go here */}
      <div className="flex-1 flex items-center justify-center text-white">
        <p className="text-2xl font-serif">Headway — Coming Soon</p>
      </div>
    </div>
  )
}
