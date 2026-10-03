import { Link } from 'react-router-dom'
import Navbar from '../components/Navbar'

export default function Landing() {
  return (
    <div className="h-screen w-full bg-black flex flex-col">
      <Navbar />

      <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
        <h1
          className="font-serif font-bold text-6xl md:text-7xl text-white leading-tight max-w-3xl"
          style={{ textShadow: '0 0 40px rgba(255, 90, 46, 0.45)' }}
        >
          What's your commute score?
        </h1>

        <p className="text-gray text-lg md:text-xl mt-6 max-w-xl">
          Headway calculates the best spots to live off campus.
        </p>

        <Link
          to="/app"
          className="mt-10 bg-orange text-black font-medium px-8 py-3 rounded-full text-lg hover:opacity-90 transition-opacity"
        >
          Check an address →
        </Link>
      </div>
    </div>
  )
}
