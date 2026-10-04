const SWATCH_OPACITIES = [0.1, 0.22, 0.34, 0.46, 0.58]

export default function Legend() {
  return (
    <div
      className="rounded-xl px-4 py-3.5 flex flex-col gap-2.5"
      style={{ background: 'rgba(11,11,12,0.92)', border: '1px solid #2a2a2e' }}
    >
      <span
        className="text-[#a9a69f]"
        style={{ fontFamily: 'Geist', fontWeight: 600, fontSize: '10.5px', letterSpacing: '0.63px' }}
      >
        STOP FREQUENCY
      </span>

      <div className="flex items-center gap-2">
        <span className="text-[#8e8c87] text-xs">Low</span>
        <div className="flex gap-[3px]">
          {SWATCH_OPACITIES.map((opacity) => (
            <div
              key={opacity}
              className="w-7 h-2.5 rounded-sm"
              style={{
                border: '1px solid #2a2a2e',
                background: `rgba(255,90,46,${opacity})`,
              }}
            />
          ))}
        </div>
        <span className="text-[#8e8c87] text-xs">High</span>
      </div>
    </div>
  )
}
