import { useEffect } from 'react'
import { Link } from 'react-router'
import { useMoney } from '../Currency'
import { useAsync } from '../hooks'

type Preview = { finished_at: string | null; count: number; titles: string[]; status: string | null }
async function load(): Promise<Preview> {
  const res = await fetch('/api/advisor/summary')
  if (!res.ok) throw new Error('Review unavailable')
  return res.json()
}

export function AdvisorPreview() {
  const { hidden } = useMoney()
  const { data, reload } = useAsync(load, [])
  useEffect(() => {
    const timer = window.setInterval(reload, 60_000)
    return () => window.clearInterval(timer)
  }, [reload])
  if (hidden || !data) return null
  const active = data.status === 'queued' || data.status === 'running'
  return <section className="card advisor-preview">
    <div><span className="muted small">🧭 Financial advisor</span><h3>{active ? 'Your review is in progress' : data.finished_at ? `${data.count} findings in your latest review` : 'Your first financial review'}</h3>
      <p className="muted small">{data.status === 'failed' ? 'The latest attempt needs another try. Open the advisor for details.' : data.titles.length ? data.titles.join(' · ') : data.finished_at ? 'No new findings need your attention.' : 'Set your goals and get an evidence-backed review of your finances.'}</p></div>
    <Link className="btn soft" to="/advisor">{data.finished_at || active ? 'Open review →' : 'Get started →'}</Link>
  </section>
}
