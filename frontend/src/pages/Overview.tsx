import { useMoney } from '../Currency'
import { Link } from 'react-router'
import type { Summary } from '../api'
import { categoryStyle } from '../colors'
import { BreakdownCard } from '../components/BreakdownCard'
import { HistoryChart } from '../components/HistoryChart'
import { HoldingsTreemap } from '../components/HoldingsTreemap'
import { MiniDonut } from '../components/MiniDonut'
import { RefreshButton } from '../components/RefreshButton'
import { ago, greeting, pct, signedPct } from '../format'
import { useCountUp } from '../hooks'
import type { Slice } from '../scenario'

type Props = { summary: Summary; onRefreshed: (s: Summary) => void }

export function Overview({ summary, onRefreshed }: Props) {
  const { money, signedMoney } = useMoney()
  const total = useCountUp(summary.total)
  const categories = Object.entries(summary.categories)

  const categoryIndex = (c: string) => categories.findIndex(([k]) => k === c)
  const accountCategory = new Map(summary.accounts.map(a => [a.name, a.category]))
  const categorySlices: Slice[] = categories.map(([label, value]) => ({
    label, value, actualValue: value,
    share: summary.total ? value / summary.total : 0,
    actualShare: summary.total ? value / summary.total : 0,
    // Cash counts wherever it's held, so say how it's held when that isn't a cash account.
    parts: Object.entries(summary.category_accounts?.[label] ?? {}).map(([account, v]) => {
      const home = accountCategory.get(account) ?? label
      return {
        label: account, href: `/accounts/${encodeURIComponent(account)}`,
        value: v,
        icon: categoryStyle(home, categoryIndex(home)).emoji,
        note: home === label ? undefined : home === 'crypto' ? 'stablecoins' : home === 'investments' ? 'uninvested' : home,
      }
    }),
  }))
  const broken = summary.accounts.filter(a => a.last_error)

  return (
    <div className="page">
      <section className="hero">
        <div className="hero-blob a" />
        <div className="hero-blob b" />
        <div className="hero-content">
          <p className="hero-hello">{greeting()} 👋</p>
          <p className="hero-label">You're worth</p>
          <h1 className="hero-total">{money(total)}</h1>
          <div className="hero-changes">
            {Object.entries(summary.changes).map(([label, c]) => (
              <span key={label} className={`change-chip ${c.value >= 0 ? 'up' : 'down'}`} title={`vs ${new Date(c.ts).toLocaleString('en-GB')}`}>
                <b>{label}</b> {c.value >= 0 ? '▲' : '▼'} {signedMoney(c.value)}
                <span className="sub">{signedPct(c.previous ? c.value / c.previous : 0)}</span>
              </span>
            ))}
          </div>
          <div className="hero-foot">
            <span>Updated {ago(summary.ts)}</span>
            <RefreshButton onRefreshed={onRefreshed} />
          </div>
        </div>
        <div className="hero-cats">
          {categories.map(([cat, value]) => (
            <div key={cat} className="hero-cat">
              <span className="hero-cat-emoji">{categoryStyle(cat, categoryIndex(cat)).emoji}</span>
              <span className="hero-cat-name">{cat}</span>
              <span className="hero-cat-value">{money(value)}</span>
              <span className="hero-cat-pct">{pct(summary.total ? value / summary.total : 0)}</span>
            </div>
          ))}
        </div>
      </section>

      {broken.length > 0 && (
        <div className="banner warn">
          <span>🚧</span>
          <div>
            <b>{broken.length === 1 ? '1 account is' : `${broken.length} accounts are`} showing old numbers.</b>{' '}
            {broken.map(a => a.name).join(', ')} - their last fetch failed, so the last good values are carried forward.
          </div>
        </div>
      )}

      <div className="grid two-one">
        <HistoryChart />
        <BreakdownCard
          title="Where it lives"
          emoji="🍩"
          slices={categorySlices}
          icon={c => categoryStyle(c, categoryIndex(c)).emoji}
          colorOf={c => categoryStyle(c, categoryIndex(c)).color}
          showDelta={false}
          labelOf={c => c.charAt(0).toUpperCase() + c.slice(1)}
          partsLabel="Held in"
        />
      </div>

      <section>
        <h2 className="section-title"><span className="emoji">🗂️</span> Accounts</h2>
        <div className="account-grid">
          {summary.accounts.map(a => {
            const style = categoryStyle(a.category, categoryIndex(a.category))
            return (
              <Link key={a.name} to={`/accounts/${encodeURIComponent(a.name)}`} className="account-card" style={{ ['--c' as string]: style.color }}>
                <div className="account-top">
                  <span className="account-emoji">{style.emoji}</span>
                  {a.last_error ? <span className="status bad" title={a.last_error}>⚠️ stale</span> : <span className="status ok">● live</span>}
                </div>
                <div className="account-main">
                  <div>
                    <div className="account-name">{a.name}</div>
                    <div className="account-value">{money(a.value)}</div>
                  </div>
                  <MiniDonut account={a} />
                </div>
                <div className="account-meta">
                  <span>{pct(summary.total ? a.value / summary.total : 0)} of total</span>
                  <span>{a.holdings.length} holding{a.holdings.length === 1 ? '' : 's'}</span>
                </div>
                <div className="account-bar"><span style={{ width: `${summary.total ? (a.value / summary.total) * 100 : 0}%` }} /></div>
                <div className="account-foot muted small">
                  {a.last_error ? `Last good fetch ${ago(a.last_success)}` : `Fetched ${ago(a.fetched_at ?? a.last_success)}`}
                </div>
              </Link>
            )
          })}
        </div>
      </section>

      <HoldingsTreemap summary={summary} />
    </div>
  )
}
