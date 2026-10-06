import { useMoney } from '../Currency'
import { ChartFrame, ChartTooltip as Tooltip } from './ChartTooltip'
import { useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { categoryStyle, PALETTE } from '../colors'
import { signedPct } from '../format'
import { useAsync } from '../hooks'

const RANGES: { label: string; days: number | null }[] = [
  { label: '1W', days: 7 },
  { label: '1M', days: 30 },
  { label: '3M', days: 90 },
  { label: '1Y', days: 365 },
  { label: 'All', days: null },
]

export function HistoryChart() {
  const { money, moneyCompact, signedMoney, hidden } = useMoney()
  const [range, setRange] = useState(3)
  const [group, setGroup] = useState<'category' | 'account'>('category')
  const days = RANGES[range].days
  const { data, error, loading } = useAsync(() => api.history(days, group), [days, group])

  const colors = useMemo(() => {
    const map: Record<string, string> = {}
    data?.keys.forEach((k, i) => (map[k] = group === 'category' ? categoryStyle(k, i).color : PALETTE[i % PALETTE.length]))
    return map
  }, [data, group])

  const points = useMemo(
    () => data?.points.map(p => ({ t: new Date(p.ts).getTime(), total: p.total, ...p.values })) ?? [],
    [data],
  )
  const first = points[0]?.total ?? 0
  const last = points[points.length - 1]?.total ?? 0
  const change = last - first
  const spanDays = points.length > 1 ? (points[points.length - 1].t - points[0].t) / 86400000 : 0

  const tickFormat = (t: number) =>
    new Date(t).toLocaleDateString('en-GB', spanDays > 200 ? { month: 'short', year: '2-digit' } : spanDays > 3 ? { day: 'numeric', month: 'short' } : { hour: '2-digit', minute: '2-digit' })

  return (
    <section className="card history">
      <header className="card-head wrap">
        <div>
          <h3><span className="emoji">🚀</span> How it's grown</h3>
          {points.length > 1 && (
            <p className={`history-change ${change >= 0 ? 'up' : 'down'}`}>
              {change >= 0 ? '▲' : '▼'} {signedMoney(change)} <span>({signedPct(first ? change / first : 0)})</span>
              <span className="muted"> over {RANGES[range].label === 'All' ? 'all time' : RANGES[range].label}</span>
            </p>
          )}
        </div>
        <div className="controls">
          <div className="pills" role="tablist" aria-label="Group by">
            {(['category', 'account'] as const).map(g => (
              <button key={g} className={group === g ? 'on' : ''} onClick={() => setGroup(g)}>
                {g === 'category' ? 'Categories' : 'Accounts'}
              </button>
            ))}
          </div>
          <div className="pills" role="tablist" aria-label="Range">
            {RANGES.map((r, i) => (
              <button key={r.label} className={range === i ? 'on' : ''} onClick={() => setRange(i)}>{r.label}</button>
            ))}
          </div>
        </div>
      </header>

      <div className={`chart-area ${loading ? 'loading' : ''}`}>
        {error && <p className="error-text">Couldn't load history: {error}</p>}
        {!error && points.length < 2 && !loading && <p className="empty">Not enough history yet - check back after a few runs ⏳</p>}
        {points.length >= 2 && (
          <ChartFrame><ResponsiveContainer width="100%" height={320}>
            <AreaChart data={points} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
              <defs>
                {data!.keys.map(k => (
                  <linearGradient key={k} id={`grad-${k.replace(/\W/g, '')}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={colors[k]} stopOpacity={0.85} />
                    <stop offset="100%" stopColor={colors[k]} stopOpacity={0.35} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid vertical={false} stroke="var(--grid)" strokeDasharray="4 6" />
              <XAxis
                dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']}
                tickFormatter={tickFormat} tick={{ fill: 'var(--muted)', fontSize: 12 }}
                axisLine={false} tickLine={false} minTickGap={40}
              />
              <YAxis
                tickFormatter={moneyCompact} tick={hidden ? false : { fill: 'var(--muted)', fontSize: 12 }}
                axisLine={false} tickLine={false} width={hidden ? 8 : 64}
              />
              <Tooltip
                cursor={{ stroke: 'var(--ink)', strokeOpacity: 0.25, strokeWidth: 2 }}
                content={({ active, payload, label }) =>
                  active && payload?.length ? (
                    <div className="tooltip">
                      <div className="tooltip-title">{new Date(label as number).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}</div>
                      <div className="tooltip-total">{money((payload[0].payload as { total: number }).total)}</div>
                      {[...payload].reverse().map(p => (
                        <div key={String(p.dataKey)} className="tooltip-row">
                          <span className="swatch" style={{ background: colors[String(p.dataKey)] }} />
                          <span>{String(p.dataKey)}</span>
                          <b>{money(Number(p.value))}</b>
                        </div>
                      ))}
                    </div>
                  ) : null
                }
              />
              {[...data!.keys].reverse().map(k => (
                <Area
                  key={k} type="monotone" dataKey={k} stackId="1"
                  stroke={colors[k]} strokeWidth={2} fill={`url(#grad-${k.replace(/\W/g, '')})`}
                  animationDuration={800}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer></ChartFrame>
        )}
      </div>
      {data && (
        <div className="chips">
          {data.keys.map((k, i) => (
            <span key={k} className="chip" style={{ ['--c' as string]: colors[k] }}>
              {group === 'category' ? categoryStyle(k, i).emoji : '●'} {k}
            </span>
          ))}
        </div>
      )}
    </section>
  )
}
