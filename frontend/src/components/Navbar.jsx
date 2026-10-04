import { Link } from 'react-router-dom'

export default function Navbar() {
  return (
    <nav className="sticky top-0 z-20 w-full h-20 bg-black border-b border-gray/30 grid grid-cols-3 items-center px-8">
      <span className="text-white font-serif text-xl">Headway</span>

      <div className="flex items-center justify-center gap-10">
        <a href="#about" className="text-gray hover:text-white transition-colors">About</a>
        <a href="#team" className="text-gray hover:text-white transition-colors">Team</a>
        <a
          href="https://github.com/Olisaemeka-Paul-Ani/Headway"
          target="_blank"
          rel="noopener noreferrer"
          className="text-gray hover:text-white transition-colors"
        >
          GitHub
        </a>
      </div>

      <div className="flex justify-end">
        <Link
          to="/app"
          className="bg-orange text-black font-medium px-5 py-2 rounded-full text-sm hover:opacity-90 transition-opacity"
        >
          Try app
        </Link>
      </div>
    </nav>
  )
}
