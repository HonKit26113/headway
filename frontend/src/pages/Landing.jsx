import { Link } from 'react-router-dom'
import Navbar from '../components/Navbar'

const TEAM = [
  { name: 'Cedric H.', study: 'CS, UBC' },
  { name: 'Herman L.', study: 'CS, UBC' },
  { name: 'Daniel L.', study: 'CS, UBC' },
  { name: 'Olisaemeka A.', study: 'DS + CS, SFU' },
]

const FACTORS = [
  { icon: '🚌', label: 'Commute' },
  { icon: '⏱', label: 'Frequency' },
  { icon: '🌙', label: 'Late-night' },
  { icon: '🚶', label: 'Walk' },
]

export default function Landing() {
  return (
    <div className="bg-black">
      <Navbar />

      <section className="relative h-screen overflow-hidden flex flex-col items-center justify-center px-6 text-center">
        <div className="blob blob-1 w-[500px] h-[500px] bg-orange left-[-100px] top-[10%]" />
        <div className="blob blob-2 w-[450px] h-[450px] bg-gray right-[-120px] bottom-[5%]" />

        <div className="relative z-10 flex flex-col items-center">
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
      </section>

      <section id="about" className="py-32 px-6 border-t border-gray/20">
        <div className="flex flex-col md:flex-row items-center gap-16 max-w-5xl mx-auto">
          <div className="flex-1 text-center md:text-left">
            <h2 className="font-serif text-4xl md:text-5xl text-white">About</h2>
            <p className="text-gray text-lg mt-6">
              Headway scores any address by how well transit connects it to campus —
              commute time, bus frequency, late-night service, and walk distance,
              weighted into a single 0–10 score. Built for students who want a place
              that works, not just one that's cheap.
            </p>

            <div className="flex flex-wrap items-center justify-center md:justify-start gap-10 mt-10">
              {FACTORS.map((factor) => (
                <div key={factor.label} className="flex flex-col items-center gap-2">
                  <span className="text-3xl">{factor.icon}</span>
                  <span className="text-gray text-sm">{factor.label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="flex-1 w-full relative">
            <img
              src="/map-preview-dark.png"
              alt="Map preview centered on SFU"
              className="w-full rounded-2xl border border-gray/30"
            />
            <svg
              viewBox="0 0 768 768"
              className="absolute inset-0 w-full h-full pointer-events-none"
              fill="none"
            >
              <path
                d="M 60 600 C 220 520, 260 420, 400 400 S 600 320, 700 180"
                stroke="#FF5A2E"
                strokeWidth="4"
                strokeLinecap="round"
                opacity="0.85"
              />
              <path
                d="M 100 120 C 220 220, 380 260, 420 400 S 520 600, 680 680"
                stroke="#FF5A2E"
                strokeWidth="4"
                strokeLinecap="round"
                opacity="0.6"
              />
              {[[60,600],[400,400],[700,180],[100,120],[680,680]].map(([cx, cy]) => (
                <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="6" fill="#FF5A2E" />
              ))}
            </svg>
          </div>
        </div>
      </section>

      <section id="team" className="py-32 px-6 text-center border-t border-gray/20">
        <h2 className="font-serif text-4xl md:text-5xl text-white mb-16">Team</h2>
        <div className="flex flex-wrap items-start justify-center gap-16 max-w-3xl mx-auto">
          {TEAM.map((member) => (
            <div key={member.name}>
              <div className="text-white text-lg">{member.name}</div>
              <div className="text-gray text-sm mt-1">{member.study}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
