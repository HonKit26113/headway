import { useEffect, useRef, useState } from 'react'
import { searchAddress } from '../lib/geocoding'

const DEBOUNCE_MS = 400

export function useGeocode(query) {
  const [suggestions, setSuggestions] = useState([])
  const timeoutRef = useRef(null)
  const requestIdRef = useRef(0)

  useEffect(() => {
    clearTimeout(timeoutRef.current)

    if (!query || query.trim().length < 3) {
      setSuggestions([])
      return
    }

    timeoutRef.current = setTimeout(async () => {
      const thisRequest = ++requestIdRef.current
      const results = await searchAddress(query)
      if (thisRequest === requestIdRef.current) {
        setSuggestions(results)
      }
    }, DEBOUNCE_MS)

    return () => clearTimeout(timeoutRef.current)
  }, [query])

  return suggestions
}
