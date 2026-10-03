const MOCK_RESULT = {
  address: '4500 Kingsway',
  city: 'Metrotown',
  score: 8.4,
  factors: [
    { label: 'Commute to campus', value: '24 min' },
    { label: 'Peak frequency', value: 'every 6 min' },
    { label: 'Last trip home', value: '1:15 am' },
    { label: 'Walk to nearest stop', value: '5 min' },
  ],
}

export default function ScorePanel({ result = MOCK_RESULT, isSample = true }) {
  return (
    <aside
      className="w-[400px] h-full flex flex-col gap-6 p-8 overflow-y-auto"
      style={{ background: '#0b0b0c', borderLeft: '1px solid #1f1f22' }}
    >
      <div className="flex items-center justify-between">
        <span
          className="text-[#a9a69f]"
          style={{ fontFamily: 'Geist', fontWeight: 600, fontSize: '11px', letterSpacing: '0.66px' }}
        >
          SCORE
        </span>
        {isSample && (
          <span
            className="rounded-full px-2.5 py-1 text-[#a9a69f]"
            style={{ border: '1px solid #2a2a2e', fontFamily: 'Geist', fontSize: '11px' }}
          >
            Sample data
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <span style={{ fontFamily: 'Geist', fontWeight: 500, fontSize: '15px', color: '#edebe6' }}>
          {result.address}
        </span>
        <span style={{ fontFamily: 'Geist', fontWeight: 400, fontSize: '12px', color: '#a9a69f' }}>
          {result.city}
        </span>
      </div>

      <div
        className="pb-6"
        style={{ borderBottom: '1px solid #1f1f22', fontFamily: 'Instrument Serif', fontSize: '72px', lineHeight: '72px', color: '#ff5a2e' }}
      >
        {result.score.toFixed(1)}
      </div>

      <div className="flex flex-col">
        {result.factors.map((factor) => (
          <div
            key={factor.label}
            className="flex items-center justify-between py-3"
            style={{ borderBottom: '1px solid #1f1f22' }}
          >
            <span style={{ fontFamily: 'Geist', fontWeight: 400, fontSize: '12px', color: '#8e8c87' }}>
              {factor.label}
            </span>
            <span style={{ fontFamily: 'Geist', fontWeight: 500, fontSize: '15px', color: '#edebe6' }}>
              {factor.value}
            </span>
          </div>
        ))}
      </div>
    </aside>
  )
}
