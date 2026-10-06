import { useMoney } from '../Currency'
import { ChartFrame, ChartTooltip as Tooltip } from '../components/ChartTooltip'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import { api, type Summary } from '../api'
import { categoryStyle, KIND_EMOJI } from '../colors'
import { BreakdownCard } from '../components/BreakdownCard'
import { CountUp } from '../components/CountUp'
import { DetailsModal } from '../components/DetailsModal'
import { WalletBreakdown } from '../components/WalletBreakdown'
import { HoldingsTable } from '../components/HoldingsTable'
import { RefreshButton } from '../components/RefreshButton'
import { CloseButton, Modal } from '../components/Modal'
import { flag, sectorEmoji, sectorShort } from '../flags'
import { ago, pct } from '../format'
import { useAsync, useStoredState } from '../hooks'
import { breakdown, buildRows, components, EMPTY_SCENARIO, isEmpty, type Row, type Scenario, type Slice } from '../scenario'

export function AccountPage({ onRefreshed }: { onRefreshed: (summary: Summary) => void }) {
  const { money, moneyCompact } = useMoney()
  const name = decodeURIComponent(useParams().name ?? '')
  const chain = useParams().chain
  const wallet = useParams().wallet
  const { data: detail, error, loading, reload } = useAsync(() => chain ? api.chain(name, chain) : wallet ? api.wallet(name, wallet) : api.account(name), [name, chain, wallet])
  const [scenario, setScenario] = useStoredState<Scenario>(`networth:scenario:${name}:${chain ?? wallet ?? ""}`, EMPTY_SCENARIO)
  const [editing, setEditing] = useState(false)
  const [productsOpen, setProductsOpen] = useState(false)
  const [details, setDetails] = useState<Row | null>(null)

  const rows = useMemo(() => (detail ? buildRows(detail, scenario) : []), [detail, scenario])
  const visible = rows.filter(r => !r.hidden)
  const sandboxTotal = visible.reduce((s, r) => s + r.value, 0)
  const actualTotal = visible.reduce((s, r) => s + r.actualValue, 0)
  const hasEdits = rows.some(r => r.edited)
  const hiddenCount = rows.filter(r => r.hidden).length
  const classified = detail && Object.keys(detail.classifications).length > 0

  const products = useMemo(() => breakdown(rows, 'product'), [rows])
  const countries = useMemo(() => breakdown(rows, 'country'), [rows])
  const sectors = useMemo(() => breakdown(rows, 'sector'), [rows])

  if (loading && !detail) return <div className="page"><div className="loading-card">🔍 Looking up {name}… <span className="muted">(investment accounts may take a few seconds on their first visit)</span></div></div>
  if (error || !detail) return <div className="page"><div className="banner bad">😬 {error ?? 'Not found'} <Link to="/">Back to overview</Link></div></div>

  const style = categoryStyle(detail.category)
  const productIcon = (asset: string) => (asset === 'Cash' ? '💷' : KIND_EMOJI[rows.find(r => r.asset === asset)?.classification?.kind ?? ''] ?? '🔹')
  const realCountries = countries.filter(c => !['Cash', 'Unknown', 'Other'].includes(c.label))
  const cash = visible.filter(r => r.asset === 'GBP').reduce((s, r) => s + r.value, 0)
  const biggest = [...visible].sort((a, b) => b.value - a.value).find(r => r.asset !== 'GBP')
  const usShare = countries.find(c => c.label === 'United States')?.share ?? 0

  return (
    <div className="page">
      <Link to={chain || wallet ? `/accounts/${encodeURIComponent(name)}` : "/"} className="back">← {chain || wallet ? name : "Overview"}</Link>

      <section className="hero account-hero" style={{ ['--c' as string]: style.color }}>
        <div className="hero-blob a" />
        <div className="hero-blob b" />
        <div className="hero-content">
          <p className="hero-hello">{style.emoji} {detail.category}</p>
          <h1 className="hero-name">{wallet ? `${wallet.slice(0, 7)}…${wallet.slice(-5)}` : detail.name}</h1>
          <h2 className="hero-total small"><CountUp value={sandboxTotal} format={money} /></h2>
          {hasEdits && <p className="hero-sandbox">✏️ Sandbox values · actually {money(actualTotal)}</p>}
          <div className="hero-foot">
            <span>
              {detail.last_error ? `⚠️ Last fetch failed - showing values from ${ago(detail.last_success)}` : `Fetched ${ago(detail.fetched_at ?? detail.last_success)}`}
              {hiddenCount > 0 && ` · ${hiddenCount} hidden`}
            </span>
            {/* Chains and wallets are read in one fetch of their account, so that's the smallest thing to refresh. */}
            <RefreshButton account={name} onRefreshed={s => { onRefreshed(s); reload() }} />
            <div className="hero-actions">
              {!isEmpty(scenario) && (
                <button className="btn glass" onClick={() => setScenario(EMPTY_SCENARIO)}>↺ Reset all</button>
              )}
              <button className={`btn glass ${editing ? 'on' : ''}`} onClick={() => setEditing(e => !e)}>
                {editing ? '✅ Done' : '✏️ Sandbox'}
              </button>
            </div>
          </div>
        </div>
      </section>

      {editing && (
        <div className="banner sandbox">
          <span>✏️</span>
          <div>
            <b>Sandbox.</b> Change units or values, or add holdings you don't own, and every chart updates. The <span className="delta up">+pp</span> tags
            show how each slice's share moves against your real holdings. Nothing real changes - it's saved in this browser only.
          </div>
        </div>
      )}

      {detail.wallets && <WalletBreakdown detail={detail} />}

      <div className="stats">
        <Stat emoji="🧺" label="Holdings" value={String(visible.length)} />
        {biggest && <Stat emoji="🏆" label="Biggest" value={biggest.asset} sub={pct(sandboxTotal ? biggest.value / sandboxTotal : 0)} />}
        {cash > 0 && <Stat emoji="💷" label="Cash" value={moneyCompact(cash)} sub={pct(sandboxTotal ? cash / sandboxTotal : 0)} />}
        {classified && <Stat emoji="🗺️" label="Countries" value={String(realCountries.length)} sub={usShare ? `${pct(usShare)} US` : undefined} />}
      </div>

      <div className={`grid ${classified ? 'three' : 'one'}`}>
        <BreakdownCard
          title="By product" emoji="🧺" slices={products} icon={productIcon} showDelta={hasEdits}
          partsLabel="Top holdings inside" onExpand={() => setProductsOpen(true)}
        />
        {classified && (
          <>
            <BreakdownCard title="By country" emoji="🌍" slices={countries} icon={flag} showDelta={hasEdits} note="Funds looked through" partsLabel="Held through" />
            <BreakdownCard title="By sector" emoji="🏭" slices={sectors} icon={sectorEmoji} labelOf={sectorShort} showDelta={hasEdits} partsLabel="Held through" />
          </>
        )}
      </div>

      {hasEdits && <BeforeAfter rows={products} />}

      <HoldingsTable accountName={name} rows={rows} dustToggle={detail.category === 'crypto'} setScenario={setScenario} editing={editing} canAdd={!!classified} onDetails={setDetails} />


      <Modal open={productsOpen} onClose={() => setProductsOpen(false)} className="wide">
        <ProductsExpanded rows={rows} products={products} icon={productIcon} showDelta={hasEdits} onClose={() => setProductsOpen(false)} />
      </Modal>
      <DetailsModal symbol={details?.classification?.symbol ?? null} title={details?.name} onClose={() => setDetails(null)} />
    </div>
  )
}

type ExpandedProps = { rows: Row[]; products: Slice[]; icon: (label: string) => string; showDelta: boolean; onClose: () => void }

/** The product breakdown, bigger, optionally with funds split into what they hold. */
function ProductsExpanded({ rows, products, icon, showDelta, onClose }: ExpandedProps) {
  const [split, setSplit] = useStoredState('networth:split-funds', false)
  const parts = useMemo(() => (split ? components(rows) : products), [split, rows, products])
  const funds = rows.filter(r => !r.hidden && r.classification?.kind === 'fund')
  const listed = funds.filter(r => r.classification?.holdings?.length)

  return (
    <div className="modal-body">
      <BreakdownCard
        title={split ? 'By holding, funds split' : 'By product'}
        emoji="🧺"
        slices={parts}
        icon={icon}
        showDelta={showDelta}
        max={split ? 25 : 40}
        size={260}
        partsLabel={split ? 'Held through' : 'Top holdings inside'}
        className="flat"
        actions={
          <>
            {funds.length > 0 && (
              <label className="check">
                <input type="checkbox" checked={split} onChange={e => setSplit(e.target.checked)} />
                <span>Split funds</span>
              </label>
            )}
            <CloseButton onClose={onClose} />
          </>
        }
      />
      <p className="footnote">
        {split
          ? <>Each fund is spread over the companies it holds{listed.length < funds.length && ' (where its holdings are known)'}, merged with
            anything you hold directly. Only each fund's top 10 holdings are listed - the rest is under "Rest of …".</>
          : <>Click a fund to see its top 10 holdings. Tick <b>Split funds</b> to look through every fund at once.</>}
      </p>
    </div>
  )
}

function Stat({ emoji, label, value, sub }: { emoji: string; label: string; value: string; sub?: string }) {
  return (
    <div className="stat">
      <span className="stat-emoji">{emoji}</span>
      <div>
        <div className="stat-label">{label}</div>
        <div className="stat-value">{value} {sub && <span className="stat-sub">{sub}</span>}</div>
      </div>
    </div>
  )
}

function BeforeAfter({ rows }: { rows: Slice[] }) {
  const { money, moneyCompact, hidden } = useMoney()
  const data = rows.slice(0, 12).map(r => ({ label: r.label === 'GBP' ? 'Cash' : r.label, Actual: r.actualValue, Sandbox: r.value }))
  return (
    <section className="card">
      <header className="card-head">
        <h3><span className="emoji">⚖️</span> Actual vs sandbox</h3>
        <span className="muted small">Value per product</span>
      </header>
      <ChartFrame><ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} barGap={4} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" strokeDasharray="4 6" />
          <XAxis dataKey="label" tick={{ fill: 'var(--muted)', fontSize: 12 }} axisLine={false} tickLine={false} interval={0} />
          <YAxis tickFormatter={moneyCompact} tick={hidden ? false : { fill: 'var(--muted)', fontSize: 12 }} axisLine={false} tickLine={false} width={hidden ? 8 : 64} />
          <Tooltip
            cursor={{ fill: 'var(--hover)' }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <div className="tooltip">
                  <div className="tooltip-title">{label}</div>
                  {payload.map(p => (
                    <div key={String(p.dataKey)} className="tooltip-row">
                      <span className="swatch" style={{ background: p.color }} />
                      <span>{String(p.dataKey)}</span>
                      <b>{money(Number(p.value))}</b>
                    </div>
                  ))}
                </div>
              ) : null
            }
          />
          <Bar dataKey="Actual" fill="#c9c2e6" radius={[8, 8, 0, 0]} />
          <Bar dataKey="Sandbox" fill="#ff4fa3" radius={[8, 8, 0, 0]} />
        </BarChart>
      </ResponsiveContainer></ChartFrame>
    </section>
  )
}
