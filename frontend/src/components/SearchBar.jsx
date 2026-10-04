import { useState, useRef } from 'react'
import { fetchScore, fetchSummary, ScoreApiError } from '../lib/api'
import { useGeocode } from '../hooks/useGeocode'

export default function SearchBar({ campus, onResult, onLocationSelect, onLoadingChange, onSummaryLoadingChange }) {
  const [address, setAddress] = useState('')
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(-1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const blurTimeout = useRef(null)
  const requestIdRef = useRef(0)

  const suggestions = useGeocode(open ? address : '')

  const updateLoading = (val) => {
    setLoading(val)
    onLoadingChange?.(val)
  }

  const runScore = async (addressText, location) => {
    const thisRequest = ++requestIdRef.current
    updateLoading(true)
    setError(null)
    onResult(null) // clear any previous result so stale data can't linger on failure
    if (location) onLocationSelect?.(location)

    let data
    try {
      data = await fetchScore(addressText, campus)
    } catch (err) {
      if (thisRequest !== requestIdRef.current) return
      if (err instanceof ScoreApiError && err.status === 400) {
        setError(err.message || 'No results for that address.')
      } else {
        setError('Could not reach the scoring service. Try again in a moment.')
      }
      updateLoading(false)
      return
    }

    if (thisRequest !== requestIdRef.current) return
    // Show the score immediately - don't make the user wait on the verdict too
    onResult({ ...data, address: addressText, isSample: false, summary: null })
    updateLoading(false)

    onSummaryLoadingChange?.(true)
    const summary = await fetchSummary(data.score, data.factors, campus)
    if (thisRequest === requestIdRef.current) {
      onResult({ ...data, address: addressText, isSample: false, summary })
      onSummaryLoadingChange?.(false)
    }
  }

  const handleSelect = (suggestion) => {
    setAddress(suggestion.label)
    setOpen(false)
    setHighlighted(-1)
    runScore(suggestion.label, { lat: suggestion.lat, lon: suggestion.lon })
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!address.trim() || loading) return
    setOpen(false)
    runScore(address, null)
  }

  const handleKeyDown = (e) => {
    if (!open || suggestions.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlighted((i) => Math.min(i + 1, suggestions.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlighted((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && highlighted >= 0) {
      e.preventDefault()
      handleSelect(suggestions[highlighted])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const handleClear = () => {
    requestIdRef.current++ // invalidate any in-flight request
    setAddress('')
    setOpen(false)
    setHighlighted(-1)
    setError(null)
    updateLoading(false)
    onSummaryLoadingChange?.(false)
    onResult(null)
    onLocationSelect?.(null)
  }

  return (
    <form onSubmit={handleSubmit} className="absolute top-6 left-6 right-6 z-20">
      <div className="relative">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <input
              type="text"
              value={address}
              onChange={(e) => {
                setAddress(e.target.value)
                setOpen(true)
                setHighlighted(-1)
              }}
              onFocus={() => setOpen(true)}
              onBlur={() => {
                blurTimeout.current = setTimeout(() => setOpen(false), 150)
              }}
              onKeyDown={handleKeyDown}
              placeholder="Enter an address..."
              className="w-full rounded-full pl-5 pr-11 py-3 text-white placeholder-gray focus:outline-none"
              style={{ background: 'rgba(11,11,12,0.92)', border: '1px solid #2a2a2e' }}
            />
            {address && (
              <button
                type="button"
                onClick={handleClear}
                aria-label="Clear search"
                className="absolute right-3 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded-full text-gray hover:text-white transition-colors"
              >
                ✕
              </button>
            )}
          </div>
          <button
            type="submit"
            disabled={loading}
            className="bg-orange text-black font-medium px-6 py-3 rounded-full disabled:opacity-50 transition-opacity"
          >
            {loading ? '…' : 'Search'}
          </button>
        </div>

        {open && suggestions.length > 0 && (
          <div
            className="absolute top-full mt-2 left-0 right-[88px] z-20 rounded-xl overflow-hidden"
            style={{ background: 'rgba(11,11,12,0.97)', border: '1px solid #2a2a2e' }}
          >
            {suggestions.map((s, i) => (
              <div
                key={s.id}
                onMouseDown={(e) => {
                  e.preventDefault()
                  clearTimeout(blurTimeout.current)
                  handleSelect(s)
                }}
                className="px-4 py-3 text-sm cursor-pointer"
                style={{
                  color: '#edebe6',
                  background: i === highlighted ? 'rgba(255,90,46,0.12)' : 'transparent',
                  borderBottom: i < suggestions.length - 1 ? '1px solid #1f1f22' : 'none',
                }}
              >
                {s.label}
              </div>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div
          className="mt-2 inline-block rounded-lg px-4 py-2 text-sm text-[#a9a69f]"
          style={{ background: 'rgba(11,11,12,0.92)', border: '1px solid #2a2a2e' }}
        >
          {error}
        </div>
      )}
    </form>
  )
}
