import { useCallback, useEffect, useRef, useState } from 'react'

export function useAsync<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    load()
      .then(d => !cancelled && (setData(d), setError(null)))
      .catch(e => !cancelled && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce(n => n + 1), [])
  return { data, error, loading, reload, setData }
}

/** State mirrored to localStorage. Storage can be unavailable (private mode), so it's best-effort. */
export function useStoredState<T>(key: string, initial: T) {
  const read = () => {
    try {
      const raw = localStorage.getItem(key)
      return raw ? (JSON.parse(raw) as T) : initial
    } catch {
      return initial
    }
  }
  const [value, setValue] = useState<T>(read)
  const keyRef = useRef(key)

  useEffect(() => {
    if (keyRef.current !== key) {  // switched account: load that account's state
      keyRef.current = key
      setValue(read())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  useEffect(() => {
    try {
      localStorage.setItem(keyRef.current, JSON.stringify(value))
    } catch {
      // ignore
    }
  }, [value])

  return [value, setValue] as const
}
