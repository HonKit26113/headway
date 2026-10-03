export default function Navbar() {
  return (
    <nav className="w-full h-20 border-b border-gray/30 grid grid-cols-3 items-center px-8">
      <span className="text-white font-serif text-xl">Headway</span>

      <div className="flex items-center justify-center gap-10">
        <span className="text-gray">About</span>
        <span className="text-gray">Team</span>
        <span className="text-gray">GitHub</span>
      </div>

      <div />
    </nav>
  )
}
