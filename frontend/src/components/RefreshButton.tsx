import { useState } from 'react'
import { api, type Summary } from '../api'

type Props = {
  account?: string                       // refetch just this account; everything if left out
  onRefreshed: (summary: Summary) => void
}

/** Refetches from the source (not just the last snapshot), then says which accounts still failed. */
export function RefreshButton({ account, onRefreshed }: Props) {
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const refresh = async () => {
    setBusy(true)
    setProblem(null)
    try {
      const summary = await api.refresh(account)
      const failed = summary.accounts.filter(a => a.last_error && (!account || a.name === account))
      if (failed.length) {
        setProblem(account
          ? `Refresh failed: ${failed[0].last_error}`
          : `Refreshed, but ${failed.map(a => a.name).join(', ')} failed - hover the ⚠️ stale tags for why`)
      }
      onRefreshed(summary)
    } catch (e) {
      setProblem(`Refresh failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const label = busy ? 'Fetching…' : account ? `Refresh ${account}` : 'Refresh everything'
  return <>
    <button className="btn glass icon" onClick={refresh} disabled={busy} title={label} aria-label={label}>
      <span className={busy ? 'spin' : ''}>🔄</span>
    </button>
    {problem && <p className="hero-error">{problem}</p>}
  </>
}
