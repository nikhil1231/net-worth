import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { spendingApi, type SpendingTransaction } from '../api'
import { useMoney } from '../Currency'
import { useAsync } from '../hooks'
import { ago } from '../format'
import { TransactionMenu } from '../components/TransactionMenu'
import { TransactionLabel } from '../components/TransactionLabel'
import { SpendingSettings } from '../components/SpendingSettings'
import { PALETTE } from '../colors'

const localMonth = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London', year: 'numeric', month: '2-digit' }).format(new Date()).replace('/', '-')
const monthLabel = (m: string) => new Date(m + '-01T12:00:00').toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })
const dateLabel = (d: string) => new Date(d + 'T12:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
const errorMessage = (e: unknown) => e instanceof Error ? e.message : String(e)

export function Spending() {
  const { moneyExact: money, hidden } = useMoney()
  const [month, setMonth] = useState(localMonth)
  const [account, setAccount] = useState('')
  const { data, error, loading, reload } = useAsync(() => spendingApi.report(month, account), [month, account])
  const [tab, setTab] = useState<'activity' | 'recurring'>('activity')
  const [showIncome, setShowIncome] = useState(false)
  const [showInactive, setShowInactive] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [labelling, setLabelling] = useState<SpendingTransaction | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [actionError, setActionError] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [kind, setKind] = useState('')
  const [review, setReview] = useState(false)
  const [applyRule, setApplyRule] = useState(false)
  const [limit, setLimit] = useState(50)
  useEffect(() => { setLimit(50) }, [month, account, search, category, kind, review])
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true); setActionError(''); setNotice('')
    try { await action(); reload() } catch (e) { setActionError(errorMessage(e)) } finally { setBusy(false) }
  }
  const sync = () => act(async () => {
    const result = await spendingApi.sync()
    const failures = result.filter(r => r.error)
    if (failures.length) setActionError(failures.map(r => `${r.account}: ${r.error}`).join(' '))
    else setNotice(`Accounts synced · ${result.reduce((sum,r) => sum+r.count,0)} transactions refreshed.`)
  })
  const accountColor = (name: string) => {
    const bank = `${name} ${data?.accounts.find(a => a.name === name)?.institution ?? ''}`.toLowerCase()
    if (bank.includes('santander')) return '#ec0000'
    if (bank.includes('amex') || bank.includes('american express')) return '#006fcf'
    if (bank.includes('monzo')) return '#ff4f40'
    return PALETTE[Math.max(0, data?.accounts.findIndex(a => a.name === name) ?? 0) % PALETTE.length]
  }
  const filtered = data?.transactions.filter(r => (!category || r.category === category) && (!kind || r.kind === kind)
    && (!review || r.category === 'Uncategorised' || r.possible_transfer)
    && (!search || `${r.label ?? ''} ${r.merchant} ${r.description} ${r.account}`.toLowerCase().includes(search.toLowerCase()))) ?? []
  const subscriptions = data?.recurring ?? []
  const visibleSubscriptions = subscriptions.filter(r => showInactive || r.active)
  const connectionIssues = data?.accounts.filter(a => a.connection_status !== 'connected' && a.connection_status !== 'manual') ?? []
  const connectionLabel = (status: string) => ({ connected: 'Connected', paused: 'Paused', unlinked: 'Not linked', manual: 'Statements only', error: 'Sync failed', pending: 'Not synced', stale: 'Sync overdue', unverified: 'Unverified', unavailable: 'Unavailable' }[status] ?? 'Unverified')
  return <div className="page spending-page">
    <div className="spending-heading"><div><p className="hero-hello">Your everyday money</p><h1>Spending</h1><p className="muted">Understand your habits, bills and recurring payments.</p></div><div className="spending-controls">
      <label>Month<input aria-label="Spending month" type="month" min="2000-01" max="2100-12" value={month} onChange={e => { if (e.target.value) setMonth(e.target.value) }} /></label>
      <label>Accounts<select aria-label="Spending account" value={account} onChange={e => setAccount(e.target.value)}><option value="">All accounts</option>{data?.accounts.map(a => <option key={a.name}>{a.name}</option>)}</select></label>
      <button className="btn spending-settings-trigger" aria-label="Transaction settings" title="Transaction settings" onClick={() => setSettingsOpen(true)} disabled={busy}>
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9.5 3-.6 2.2-1.8 1L5 5.6 2.5 10l1.6 1.6v2L2.5 15 5 19.4l2.1-.6 1.8 1 .6 2.2h5l.6-2.2 1.8-1 2.1.6 2.5-4.4-1.6-1.4v-2l1.6-1.6L19 5.6l-2.1.6-1.8-1L14.5 3z"/><circle cx="12" cy="12.5" r="3.2"/></svg>
      </button>
      <button className="btn primary" disabled={busy || !data?.accounts.some(a => a.sync_enabled)} onClick={() => void sync()} aria-busy={busy}><span aria-hidden="true">↻</span> {busy ? 'Syncing…' : 'sync'}</button>
    </div></div>
    {(error || actionError) && <div className="banner bad" role="alert">{error || actionError}</div>}
    {notice && <div className="banner" role="status">{notice}</div>}
    {labelling && <TransactionLabel transaction={labelling} onSaved={reload} onClose={() => setLabelling(null)} />}
    {settingsOpen && <SpendingSettings accounts={data?.accounts ?? []} onSaved={reload} onClose={() => setSettingsOpen(false)} />}
    {loading ? <div className="loading-card">Loading your spending…</div> : data && <>
      <div className="spending-stats">
        {[['Net spending', data.summary.net_spent, `${money(data.summary.spent)} purchases − ${money(data.summary.refunds)} refunds`],
          ['Income received', data.summary.income, 'Settled income, excluding transfers'],
          ['Recurring commitments', data.summary.committed, 'Confirmed payments · monthly equivalent'],
          ['Pending outgoings', data.summary.pending, 'Separate from settled spending']].map(([label,value,note]) => <div className="card spending-stat" key={String(label)}><span className="muted small">{label}</span><strong>{money(Number(value))}</strong><span className="small muted">{note}</span></div>)}
      </div>
      <details className="card spending-coverage"><summary>Account coverage · {data.accounts.reduce((s,a) => s+a.count,0)} stored transactions</summary><p className="muted small">Charts reflect imported transactions only. Earliest and latest entries do not guarantee complete coverage. Missing months are not proof of zero spending. Transfers are excluded once classified; possible matches need review.</p>
        {data.accounts.map(a => <div className="coverage-row" key={a.name}><b>{a.name}</b><span>{a.first_date ? `${dateLabel(a.first_date)} – ${dateLabel(a.last_date!)}` : 'No transactions yet'}</span><span className="muted small">{a.type==='lunchflow' ? `Lunch Flow${a.sync_enabled ? ' · automatic sync' : ' · paused'}` : a.type==='monzo' ? 'Automatic sync' : 'Statement imports'} · updated {ago(a.last_success ?? null)}</span>{a.last_error && <span className="error-text small">{a.last_error}</span>}</div>)}
      </details>
      {!data.accounts.some(a => a.count) && <section className="card"><h3>Start with your transaction history</h3><p className="muted">Open transaction settings to connect your banks or import a statement, then sync to refresh your spending. Categories and recurring payments will appear as history builds up.</p><p className="small muted">For older Monzo history, reauthorise using the existing Monzo login command; history is captured immediately after approval.</p></section>}
      <div className="pills spending-tabs" role="group" aria-label="Spending view"><button className={tab==='activity' ? 'on' : ''} onClick={() => setTab('activity')}>Monthly activity</button><button className={tab==='recurring' ? 'on' : ''} onClick={() => setTab('recurring')}>Subscriptions & bills <span>{subscriptions.filter(r => r.active).length}</span></button></div>
      {tab==='activity' ? <>
        <div className="grid two-one">
          <section className="card"><div className="card-head"><h3>📈 Spending pace</h3><span className="small muted">Net purchases · {monthLabel(month)}</span></div>
            {hidden ? <p className="empty">Charts hidden for privacy</p> : !data.transactions.length ? <p className="empty">No transactions for this month</p> : <ResponsiveContainer width="100%" height={260}><LineChart data={data.pace}><CartesianGrid stroke="var(--grid)" vertical={false} /><XAxis dataKey="day" tickLine={false} axisLine={false} /><YAxis tickFormatter={v => money(v)} tickLine={false} axisLine={false} width={85} /><Tooltip formatter={v => money(Number(v))} labelFormatter={v => `Day ${v}`} contentStyle={{ background: 'var(--card)', borderColor: 'var(--line)', borderRadius: 12 }} /><Legend /><Line name="Selected month" dataKey="current" stroke="var(--violet)" strokeWidth={3} dot={false} connectNulls={false} /><Line name="Previous month" dataKey="previous" stroke="var(--muted)" strokeDasharray="5 5" dot={false} /></LineChart></ResponsiveContainer>}
            <p className="small muted">Settled spending minus refunds received in each month. Previous-month coverage may be incomplete.</p>
          </section>
          <section className="card"><div className="card-head"><h3>🍩 Where it went</h3>{category && <button className="btn" onClick={() => setCategory('')}>Clear</button>}</div>
            {!data.categories.length ? <p className="empty">Your categories will appear here</p> : data.categories.map((c,i) => <button key={c.category} className={`category-spend ${category===c.category ? 'selected' : ''}`} onClick={() => { setCategory(c.category); setReview(false); setKind('') }}><span>{c.category}</span><b>{money(c.amount)}</b>{!hidden && <span className="category-track"><span style={{ width: `${Math.max(0,c.amount) / Math.max(1,...data.categories.map(c => c.amount)) * 100}%`, background: ['var(--violet)','var(--pink)','var(--mango)','var(--up)'][i%4] }} /></span>}</button>)}
            <p className="small muted">Select a category to see its transactions below.</p>
          </section>
        </div>
        <section className="card"><div className="card-head"><h3>🗓️ Monthly history</h3><label className="spending-check"><input type="checkbox" checked={showIncome} onChange={e => setShowIncome(e.target.checked)} /> Include income</label></div>
          {hidden ? <p className="empty">Chart hidden for privacy</p> : <ResponsiveContainer width="100%" height={240}><BarChart data={data.history} onClick={state => { if (state.activeLabel) setMonth(String(state.activeLabel)) }} style={{ cursor: 'pointer' }}><CartesianGrid stroke="var(--grid)" vertical={false} /><XAxis dataKey="month" tickFormatter={monthLabel} tickLine={false} axisLine={false} /><YAxis tickFormatter={v => money(v)} width={85} tickLine={false} axisLine={false} /><Tooltip formatter={v => money(Number(v))} labelFormatter={v => monthLabel(String(v))} contentStyle={{ background: 'var(--card)', borderColor: 'var(--line)', borderRadius: 12 }} /><Legend /><Bar name="Purchases" dataKey="spent" fill="var(--violet)" radius={[5,5,0,0]} /><Bar name="Refunds" dataKey="refunds" fill="var(--mango)" radius={[5,5,0,0]} />{showIncome && <Bar name="Income" dataKey="income" fill="var(--up)" radius={[5,5,0,0]} />}</BarChart></ResponsiveContainer>}
          <p className="small muted">Select a month to explore its transactions. Months with no recorded transactions may have missing history.</p>
        </section>
        <section className="card"><div className="card-head wrap"><div className="transaction-heading"><h3>🧾 Transactions <span className="muted small">{filtered.length}</span></h3><div className="bank-connections" aria-label="Bank transaction connections">{data.accounts.map(a => <button type="button" key={a.name} className="bank-connection" title={`${a.connection_detail} Last successful sync: ${ago(a.last_success ?? null)}`} onClick={() => setSettingsOpen(true)}><span className="account-dot" style={{ background: accountColor(a.name) }} aria-hidden="true" /><span>{a.name}</span><span className={a.connection_status === 'connected' ? 'up' : 'muted'}><span aria-hidden="true">{a.connection_status === 'connected' ? '✓' : '✕'}</span> {connectionLabel(a.connection_status)}</span></button>)}</div></div><label className="spending-check"><input type="checkbox" checked={applyRule} onChange={e => setApplyRule(e.target.checked)} /> Apply category edits to this merchant’s past and future transactions</label></div>
          <p className="small muted">{filtered.length} matching transactions in {monthLabel(month)}{account ? ` · ${account}` : ' · all accounts'} · {data.accounts.filter(a => !account || a.name === account).reduce((sum, a) => sum + a.count, 0)} stored across all months. Change Month above to see earlier transactions.</p>
          {connectionIssues.length > 0 && <div className="banner bad" role="status">{connectionIssues.map(a => <p key={a.name}><b>{a.name}: {connectionLabel(a.connection_status)}.</b> {a.connection_detail}</p>)}<button className="btn" onClick={() => setSettingsOpen(true)}>Bank connections</button></div>}
          <div className="spending-controls transaction-filters"><input aria-label="Search transactions" placeholder="Search merchants or descriptions…" value={search} onChange={e => setSearch(e.target.value)} /><select aria-label="Filter category" value={category} onChange={e => setCategory(e.target.value)}><option value="">All categories</option>{data.category_options.map(c => <option key={c}>{c}</option>)}</select><select aria-label="Filter transaction type" value={kind} onChange={e => setKind(e.target.value)}><option value="">All types</option>{['expense','income','refund','transfer'].map(k => <option key={k}>{k}</option>)}</select><label className="spending-check"><input type="checkbox" checked={review} onChange={e => setReview(e.target.checked)} /> Needs review ({data.review_count})</label></div>
          <div className="spending-table-wrap"><table className="spending-table"><thead><tr><th>Date</th><th>Merchant / description</th><th>Account</th><th>Category</th><th>Type</th><th className="transaction-amount">Amount</th><th className="transaction-actions" aria-label="Recurring settings" /></tr></thead><tbody>{filtered.slice(0,limit).map(r => <tr key={r.id}><td className="transaction-date">{dateLabel(r.date)}{r.time && <span className="small muted">{r.time}</span>}</td><td><span className="transaction-name"><b>{hidden ? '••••' : r.merchant}</b><button type="button" className="transaction-label-trigger" aria-label={`${r.label ? 'Edit' : 'Add'} label for ${hidden ? 'transaction' : r.merchant}`} title={r.label ? 'Edit label' : 'Add label'} disabled={busy} onClick={() => setLabelling(r)}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg></button></span>{!hidden && (r.label ? <span className="small transaction-description transaction-label" title={`Your label · bank description: ${r.description}`}><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-label="Your label"><path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z" /><circle cx="7.5" cy="7.5" r="1.2" /></svg>{r.label}</span>
          : r.description!==r.merchant && <span className="small muted transaction-description">{r.description}</span>)}{r.pending ? <span className="spending-badge">Pending</span> : r.possible_transfer && <span className="spending-badge">Possible transfer · review</span>}</td><td><span className="account-dot" style={{ background: accountColor(r.account) }} aria-hidden="true" />{r.account}</td><td>{r.kind === 'transfer' ? <span className="muted" aria-label="No category for transfers">—</span> : <select aria-label={`Category for ${hidden ? 'transaction' : r.merchant}`} className={r.inferred.includes('category') ? 'inferred' : ''} title={r.inferred.includes('category') ? 'Suggested automatically' : undefined} disabled={busy} value={r.category} onChange={e => void act(() => spendingApi.edit(r.id, { category:e.target.value, apply_rule:applyRule }))}>{data.category_options.map(c => <option key={c}>{c}</option>)}</select>}</td><td><select aria-label={`Type for ${hidden ? 'transaction' : r.merchant}`} className={r.inferred.includes('kind') ? 'inferred' : ''} title={r.inferred.includes('kind') ? 'Detected automatically' : undefined} disabled={busy} value={r.kind} onChange={e => void act(() => spendingApi.edit(r.id, { kind:e.target.value }))}>{(r.amount<0 ? ['expense','transfer'] : ['income','refund','transfer']).map(k => <option key={k}>{k}</option>)}</select></td><td className={`transaction-amount ${r.amount<0 ? '' : 'up'}`}>{money(r.amount/100)}</td><td className="transaction-actions"><TransactionMenu label={hidden ? 'transaction' : r.merchant} value={r.recurring_type} disabled={busy || r.amount>=0 || r.kind!=='expense'} onChange={recurring_type => void act(() => spendingApi.edit(r.id, { recurring_type }))} /></td></tr>)}</tbody></table></div>
          {!filtered.length && <p className="empty">No transactions match this view.</p>}{filtered.length>limit && <div className="spending-show-more"><button className="btn" onClick={() => setLimit(limit+50)}>Show 50 more</button></div>}
          <p className="small muted">Use a transaction’s recurring icon to mark monthly spending or subscriptions. Recurring edits apply to all past and future expenses with the same merchant in the same bank account. Monthly spend and Monthly subscription immediately add a confirmed commitment, using the last settled charge. Transfers between your own accounts, credit-card repayments and investment top-ups are detected automatically; italic values are suggestions, and any choice you make overrides them. Choosing Savings also makes a payment a transfer.</p>
        </section>
      </> : <section className="card"><div className="card-head"><h3>🔁 Subscriptions & recurring bills</h3><label className="spending-check"><input type="checkbox" checked={showInactive} onChange={e => setShowInactive(e.target.checked)} /> Show inactive & dismissed ({subscriptions.filter(r => !r.active).length})</label></div><p className="muted">Use an expense’s recurring icon to mark it as Monthly spend or Monthly subscription to create a commitment immediately. Automatic suggestions use repeated merchant payments at a consistent cadence. Confirm real commitments or dismiss regular shopping. Expected dates are estimates. Payments missing beyond their cadence and grace period move to inactive history and stop counting towards commitments. Monthly payments become inactive after roughly two missed payments, based on recorded account activity. Cancelling here only records your decision.</p>
        {!visibleSubscriptions.length ? <p className="empty">No active recurring payments in this view. Mark one from its transaction, or show inactive history.</p> : <div className="recurring-grid">{visibleSubscriptions.map(r => <article className={`recurring-card ${!r.active ? 'inactive' : ''}`} key={r.id}><div className="card-head"><h3>{hidden ? '••••' : r.merchant}</h3><span className="spending-badge">{r.recurring_type==='subscription' ? 'Monthly subscription' : r.manual ? 'Monthly spend' : r.frequency}</span></div><p className="recurring-amount">{money(r.amount)} <span className="small muted">{r.variable ? 'last charge · variable' : 'per payment'}</span></p><p className="small muted">{money(r.monthly)} / month equivalent · {r.account}</p><p className="small">Last paid {dateLabel(r.last_date)}<br />{r.inactive ? 'Inactive · no recent payment recorded' : r.status==='cancelled' || r.status==='dismissed' ? 'Excluded from commitments' : r.overdue ? `Expected ${dateLabel(r.next_date)} · payment not seen` : `Expected ${dateLabel(r.next_date)}`}</p>{r.coverage_stale && <p className="small muted">Account history is not recent; sync before judging whether this is still paid.</p>}{r.description_contains && <p className="small muted">{hidden ? '••••' : `Only charges containing “${r.description_contains}”`}</p>}{r.price_change!==0 && <p className="small muted">Last payment {r.price_change>0 ? 'increased' : 'decreased'} by {money(Math.abs(r.price_change))}</p>}<label>Status<select aria-label={`Status for ${hidden ? 'recurring payment' : r.merchant}`} disabled={busy} value={r.status} onChange={e => void act(() => spendingApi.recurring(r,e.target.value as typeof r.status))}><option value="detected">Suggested · needs review</option><option value="confirmed">Confirmed commitment</option><option value="dismissed">Dismiss suggestion</option><option value="cancelled">Marked cancelled</option></select></label></article>)}</div>}
      </section>}
    </>}
  </div>
}
