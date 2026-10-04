import { CAMPUS_COORDS } from '../lib/campuses'

export default function CampusPicker({ campus, onChange }) {
  return (
    <div className="absolute top-24 left-6 z-10 flex gap-2">
      {Object.entries(CAMPUS_COORDS).map(([key, { label }]) => {
        const active = key === campus
        return (
          <button
            key={key}
            onClick={() => onChange(key)}
            className="rounded-full px-4 py-2 text-sm font-medium transition-colors"
            style={
              active
                ? { background: '#FF5A2E', color: '#0b0b0c' }
                : { background: 'rgba(11,11,12,0.92)', color: '#a9a69f', border: '1px solid #2a2a2e' }
            }
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
