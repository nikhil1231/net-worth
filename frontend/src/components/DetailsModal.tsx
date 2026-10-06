import { useMoney } from '../Currency'
import { ChartFrame, ChartTooltip as Tooltip } from './ChartTooltip'
import { Area, AreaChart, ResponsiveContainer, YAxis } from 'recharts'
import { api, type Details } from '../api'
import { flag, sectorEmoji } from '../flags'
import { pct } from '../format'
import { useAsync } from '../hooks'
import { CloseButton, Modal } from './Modal'

type Props = { symbol: string | null; title?: string; onClose: () => void }

/** What Yahoo Finance knows about a fund or stock. */
export function DetailsModal({ symbol, title, onClose }: Props) {
  return (
    <Modal open={!!symbol} onClose={onClose} className="details-modal">
      {symbol && <DetailsBody symbol={symbol} title={title} onClose={onClose} />}
    </Modal>
  )
}

function DetailsBody({ symbol, title, onClose }: { symbol: string; title?: string; onClose: () => void }) {
  const { data, error, loading } = useAsync(() => api.details(symbol), [symbol])
  const info = data?.info ?? {}
  const str = (k: string) => (typeof info[k] === 'string' && info[k] ? (info[k] as string) : undefined)
  const num = (k: string) => (typeof info[k] === 'number' && Number.isFinite(info[k]) ? (info[k] as number) : undefined)

  return (
    <div className="modal-body">
      <header className="modal-head">
        <div>
          <p className="muted small modal-kicker">
            {[symbol, str('fullExchangeName') ?? str('exchange'), str('typeDisp') ?? str('quoteType')].filter(Boolean).join(' · ')}
          </p>
          <h2>{str('longName') ?? str('shortName') ?? title ?? symbol}</h2>
        </div>
        <CloseButton onClose={onClose} />
      </header>

      {loading && !data && <div className="loading-card slim">🔍 Asking Yahoo Finance…</div>}
      {error && <div className="banner bad"><span>😬</span><div>{error}</div></div>}
      {data && <DetailsContent data={data} str={str} num={num} />}
    </div>
  )
}

type Getters = { str: (k: string) => string | undefined; num: (k: string) => number | undefined }

function DetailsContent({ data, str, num }: { data: Details } & Getters) {
  const isFund = str('quoteType') !== 'EQUITY'
  const { nativeMoney, nativeCompact } = useMoney()
  const sourceCurrency = str('currency') ?? 'USD'
  const quote = (value: number) => nativeMoney(value, sourceCurrency)
  const price = num('regularMarketPrice') ?? num('currentPrice') ?? num('previousClose')
  const change = num('regularMarketChangePercent')
  const low = num('fiftyTwoWeekLow')
  const high = num('fiftyTwoWeekHigh')
  const ops = data.fund?.operations ?? {}

  const facts: [string, string | undefined][] = isFund
    ? [
        ['Fund family', str('fundFamily')],
        ['Category', str('category')],
        ['Type', str('legalType')],
        ['Ongoing charge', fracPct(num('netExpenseRatio') !== undefined ? num('netExpenseRatio')! / 100 : ops['Annual Report Expense Ratio'] ?? undefined, 2)],
        ['Fund size', big(num('totalAssets') ?? num('netAssets'))],  // currency isn't given for funds
        ['Launched', date(num('fundInceptionDate'))],
        ['Yield', fracPct(num('yield'))],
        ['YTD return', fracPct(num('ytdReturn') !== undefined ? num('ytdReturn')! / 100 : undefined, 1, true)],
        ['3y avg return', fracPct(num('threeYearAverageReturn'), 1, true)],
        ['5y avg return', fracPct(num('fiveYearAverageReturn'), 1, true)],
        ['Turnover', fracPct(ops['Annual Holdings Turnover'] ?? undefined, 0)],
        ['Beta (3y)', fixed(num('beta3Year'))],
      ]
    : [
        ['Sector', str('sectorDisp') ?? str('sector')],
        ['Industry', str('industryDisp') ?? str('industry')],
        ['Country', str('country') && `${flag(str('country')!)} ${str('country')}`],
        ['Market cap', nativeCompact(num('marketCap'), ['GBp', 'GBX'].includes(sourceCurrency) ? 'GBP' : sourceCurrency)],
        ['P/E', fixed(num('trailingPE'))],
        ['Forward P/E', fixed(num('forwardPE'))],
        ['EPS', fixed(num('trailingEps'))],
        ['Dividend yield', fracPct(num('dividendYield') !== undefined ? num('dividendYield')! / 100 : undefined, 2)],
        ['Beta', fixed(num('beta'))],
        ['Profit margin', fracPct(num('profitMargins'))],
        ['Revenue growth', fracPct(num('revenueGrowth'), 1, true)],
        ['Employees', num('fullTimeEmployees')?.toLocaleString('en-GB')],
      ]
  const shownFacts = facts.filter((f): f is [string, string] => !!f[1])
  const about = str('longBusinessSummary') ?? data.fund?.description ?? undefined
  const assetClasses = Object.entries(data.fund?.asset_classes ?? {})
    .filter(([, v]) => v > 0.0005)
    .sort((a, b) => b[1] - a[1])
  const sectors = Object.entries(data.fund?.sectors ?? {}).slice(0, 8)
  const top = data.fund?.top_holdings ?? []

  return (
    <>
      <section className="details-price">
        <div>
          <div className="details-price-value">{price !== undefined ? quote(price) : '—'}</div>
          {change !== undefined && (
            <div className={`small strong ${change >= 0 ? 'up' : 'down'}`}>{change >= 0 ? '▲' : '▼'} {Math.abs(change).toFixed(2)}% today</div>
          )}
        </div>
        {low !== undefined && high !== undefined && price !== undefined && high > low && (
          <div className="range">
            <div className="muted small">52 week range</div>
            <div className="range-bar"><span style={{ left: `${Math.min(100, Math.max(0, ((price - low) / (high - low)) * 100))}%` }} /></div>
            <div className="range-ends small"><span>{quote(low)}</span><span>{quote(high)}</span></div>
          </div>
        )}
      </section>

      {data.history.length > 1 && (
        <div className="details-chart">
          <ChartFrame><ResponsiveContainer width="100%" height={120}>
            <AreaChart data={data.history} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="details-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--violet)" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="var(--violet)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <YAxis hide domain={['dataMin', 'dataMax']} />
              <Tooltip
                content={({ active, payload }) => {
                  const p = active && (payload?.[0]?.payload as Details['history'][number] | undefined)
                  return p ? (
                    <div className="tooltip">
                      <div className="tooltip-title">Week of {new Date(p.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</div>
                      <b>{quote(p.close)}</b>
                    </div>
                  ) : null
                }}
              />
              <Area type="monotone" dataKey="close" stroke="var(--violet)" strokeWidth={2} fill="url(#details-fill)" isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer></ChartFrame>
          <div className="muted small">Last 12 months, weekly</div>
        </div>
      )}

      {shownFacts.length > 0 && (
        <dl className="facts">
          {shownFacts.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      )}

      {about && <p className="details-about">{about}</p>}

      {(top.length > 0 || sectors.length > 0 || assetClasses.length > 0) && (
        <div className="details-columns">
          {top.length > 0 && (
            <div>
              <h4>Top holdings</h4>
              <Bars rows={top.map(h => [h.name ?? h.symbol, h.weight ?? 0])} />
            </div>
          )}
          {sectors.length > 0 && (
            <div>
              <h4>Sectors</h4>
              <Bars rows={sectors.map(([k, v]) => [`${sectorEmoji(k)} ${k}`, v])} />
            </div>
          )}
          {assetClasses.length > 0 && (
            <div>
              <h4>Asset mix</h4>
              <Bars rows={assetClasses.map(([k, v]) => [k.replace(/Position$/, '').replace(/^./, c => c.toUpperCase()), v])} />
            </div>
          )}
        </div>
      )}

      <p className="footnote">
        From Yahoo Finance ·{' '}
        <a href={`https://finance.yahoo.com/quote/${encodeURIComponent(data.symbol)}`} target="_blank" rel="noreferrer">open on Yahoo ↗</a>
        {str('website') && <> · <a href={str('website')} target="_blank" rel="noreferrer">website ↗</a></>}
      </p>
    </>
  )
}

function Bars({ rows }: { rows: [string, number][] }) {
  const max = Math.max(...rows.map(r => r[1]), 0.0001)
  return (
    <ul className="bars">
      {rows.map(([label, v]) => (
        <li key={label}>
          <span className="truncate" title={label}>{label}</span>
          <span className="bars-pct">{pct(v)}</span>
          <span className="bars-track"><span style={{ width: `${(v / max) * 100}%` }} /></span>
        </li>
      ))}
    </ul>
  )
}

/** Big amounts like market cap, which Yahoo gives in the listing's currency (pounds for pence listings). */
function big(v: number | undefined, currency?: string) {
  if (v === undefined) return undefined
  try {
    if (!currency) throw new Error('no currency')
    return new Intl.NumberFormat('en-GB', { style: 'currency', currency: ['GBp', 'GBX'].includes(currency) ? 'GBP' : currency, notation: 'compact', maximumFractionDigits: 1 }).format(v)
  } catch {
    return new Intl.NumberFormat('en-GB', { notation: 'compact', maximumFractionDigits: 1 }).format(v)
  }
}

function fracPct(v: number | undefined | null, digits = 1, signed = false) {
  if (v === undefined || v === null) return undefined
  return `${signed && v > 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`
}

const fixed = (v: number | undefined) => (v === undefined ? undefined : v.toFixed(2))
const date = (epoch: number | undefined) =>
  epoch === undefined ? undefined : new Date(epoch * 1000).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })
