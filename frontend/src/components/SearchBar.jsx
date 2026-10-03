import { useState } from 'react'
import { fetchScore } from '../lib/api'

export default function SearchBar({ campus, onResult }) {
  const [address, setAddress] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!address.trim() || loading) return

    setLoading(true)
    setError(null)
    try {
      const data = await fetchScore(address, campus)
      onResult({ ...data, address, isSample: false })
    } catch (err) {
      setError('Backend not ready yet — scoring API is still being built.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="absolute top-6 left-6 right-6 z-10">
      <div className="flex gap-2">
        <input
          type="text"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="Enter an address..."
          className="flex-1 rounded-full px-5 py-3 text-white placeholder-gray focus:outline-none"
          style={{ background: 'rgba(11,11,12,0.92)', border: '1px solid #2a2a2e' }}
        />
        <button
          type="submit"
          disabled={loading}
          className="bg-orange text-black font-medium px-6 py-3 rounded-full disabled:opacity-50 transition-opacity"
        >
          {loading ? '…' : 'Search'}
        </button>
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
