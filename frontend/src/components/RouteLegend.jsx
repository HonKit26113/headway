export default function RouteLegend() {
  return (
    <div
      className="absolute top-24 right-6 z-10 rounded-xl px-4 py-3 flex flex-col gap-2"
      style={{ background: 'rgba(11,11,12,0.92)', border: '1px solid #2a2a2e' }}
    >
      <div className="flex items-center gap-2 text-sm" style={{ color: '#edebe6' }}>
        <span>🚌</span>
        <div className="w-6 h-0.5" style={{ background: '#3b82f6' }} />
        <div className="w-6 h-0.5" style={{ background: '#eab308' }} />
        <span className="text-[#a9a69f]">Bus route</span>
      </div>
      <div className="flex items-center gap-2 text-sm" style={{ color: '#edebe6' }}>
        <span>🚶</span>
        <div
          className="w-6 h-0.5"
          style={{ borderTop: '2px dashed #ffffff' }}
        />
        <span className="text-[#a9a69f]">Walk</span>
      </div>
    </div>
  )
}
