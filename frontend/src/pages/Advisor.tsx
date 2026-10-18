import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { advisorApi, type AdvisorFeedback, type AdvisorFinding, type AdvisorSettingsView } from '../advisorApi'
import { useMoney } from '../Currency'
import { useAsync } from '../hooks'
import './advisor.css'

const when = (date: string | null) => date ? new Date(date).toLocaleString('en-GB', { timeZone: 'Europe/London', dateStyle: 'medium', timeStyle: 'short' }) : 'Not scheduled'
const message = (e: unknown) => e instanceof Error ? e.message : String(e)
const handled = new Set(['dismissed', 'incorrect', 'known'])

export function Advisor() {
  const { hidden, money } = useMoney()
  const { data, error, reload, setData } = useAsync(advisorApi.overview, [])
  const [selected, setSelected] = useState<number | null>(null)
  const { data: historical, error: historyError, reload: reloadHistory } = useAsync(() => selected ? advisorApi.history(selected) : Promise.resolve(null), [selected])
  const [showHandled, setShowHandled] = useState(false)
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const active = data?.runs.find(r => r.status === 'queued' || r.status === 'running')
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => { reload(); reloadHistory() }, 2500)
    return () => window.clearInterval(timer)
  }, [active?.id, active?.status, reload, reloadHistory])

  if (hidden) return <div className="page"><section className="card"><h1>Financial reviews are hidden</h1><p className="muted">Use Show values in the navigation to view your review and personal brief.</p></section></div>
  if (!data) return <div className="page"><div className={error ? 'banner bad' : 'loading-card'}>{error || 'Preparing your financial review…'}{error && <button className="btn" onClick={reload}>Retry</button>}</div></div>

  const run = selected ? (historical?.id === selected ? historical : null) : data.latest
  const report = run?.report
  const findings = (report?.findings ?? []).map(f => ({ ...f, ...(data.feedback[f.topic] ?? {}) }))
    .filter(f => showHandled || !handled.has(f.feedback))
    .sort((a, b) => ['attention', 'review', 'information'].indexOf(a.priority) - ['attention', 'review', 'information'].indexOf(b.priority))
  const portfolio = report?.evidence.portfolio?.facts
  const spending = report?.evidence.spending?.facts
  const number = (v: unknown) => typeof v === 'number' ? money(v) : '—'

  async function start() {
    setBusy(true); setActionError('')
    try { await advisorApi.run(); setSelected(null); reload() }
    catch (e) { setActionError(message(e)) }
    finally { setBusy(false) }
  }
  function feedback(topic: string, value: AdvisorFeedback) {
    setData(current => current ? { ...current, feedback: { ...current.feedback, [topic]: value } } : current)
  }

  return <div className="page advisor-page">
    <section className="settings-head advisor-heading">
      <div><p className="advisor-eyebrow">YOUR MONEY, IN CONTEXT</p><h1>Your financial review</h1><p className="muted">Changes worth a closer look, backed by your recorded finances.</p></div>
      <button className="btn primary" disabled={busy || !!active} onClick={start}>{busy ? 'Queuing…' : active ? `${active.status === 'queued' ? 'Queued' : 'Reviewing'}…` : 'Run a review'}</button>
    </section>
    {(actionError || error || historyError) && <div role="alert" className="banner bad">{actionError || error || historyError}</div>}
    <div className="advisor-schedule"><span>Next review: <strong>{data.settings.next_run ? when(data.settings.next_run) : 'Manual only'}</strong> · London time</span><a href="#advisor-brief">Edit your brief & schedule ↓</a></div>

    {!!data.runs.length && <div className="advisor-history"><label htmlFor="review-history">Review history</label><select id="review-history" value={selected ?? ''} onChange={e => setSelected(e.target.value ? Number(e.target.value) : null)}>
      <option value="">Latest completed review</option>
      {data.runs.map(r => <option key={r.id} value={r.id}>#{r.id} · {when(r.created_at)} · {r.status}</option>)}
    </select><label className="check"><input type="checkbox" checked={showHandled} onChange={e => setShowHandled(e.target.checked)} /> Include dismissed & already known</label></div>}
    {selected && historical?.id !== selected && !historyError && <div className="loading-card">Loading review…</div>}
    {run?.error && <div className="banner bad">{run.error}</div>}
    {!selected && data.runs[0]?.status === 'failed' && <div className="banner warn">The latest attempt failed: {data.runs[0].error} {data.latest ? 'The last completed review is shown below.' : ''}</div>}
    {run && !report && !run.error && <section className="card"><p>This review is {run.status}. It continues after you close this page.</p></section>}
    {report && <>
      <div className="advisor-stats">
        <section className="card"><span className="muted small">Recorded total</span><strong>{number(portfolio?.total_gbp)}</strong><span className="muted small">Snapshot: {typeof portfolio?.snapshot_at === 'string' ? when(portfolio.snapshot_at) : 'No snapshot'}</span></section>
        <section className="card"><span className="muted small">Recorded net spending</span><strong>{number(spending?.net_spent_gbp)}</strong><span className="muted small">{report.period.start} → {report.period.end}</span></section>
        <section className="card"><span className="muted small">This review</span><strong>{findings.length} findings</strong><span className="muted small">{report.mode === 'assisted' ? 'With model commentary' : 'Calculated checks'} · {run?.finished_at ? when(run.finished_at) : ''}</span></section>
      </div>
      <section className="card advisor-summary"><h2>Your week in view</h2><p>{report.summary}</p>{report.warning && <p className="muted small">{report.warning}</p>}<p className="muted small">Written findings use GBP. Dashboard amounts follow your currency selection.</p></section>
      <section aria-label="Review findings" className="advisor-findings">
        {findings.map(f => <Finding key={`${run?.id}:${f.topic}`} finding={f} onSaved={value => feedback(f.topic, value)} />)}
        {!findings.length && <section className="card"><h2>No new findings to review</h2><p className="muted">No checks crossed your thresholds, or these findings are already handled. You can include them using the filter above.</p></section>}
      </section>
      <details className="card advisor-evidence"><summary>Review scope & recorded facts</summary><ul>{report.limitations.map(l => <li key={l}>{l}</li>)}</ul>
        {Object.entries(report.evidence).map(([ref, e]) => <details key={ref}><summary>{e.title}</summary><Link to={e.href}>Open source page →</Link><pre>{JSON.stringify(e.facts, null, 2)}</pre></details>)}
        <p className="muted small">{run?.usage.total_tokens ? `${run.usage.total_tokens.toLocaleString()} tokens` : 'No model token usage recorded'}{run?.usage.cost !== undefined ? ` · $${run.usage.cost.toFixed(4)} provider-reported cost` : ''}</p>
      </details>
    </>}
    {!data.runs.length && <section className="card advisor-empty"><span aria-hidden>🧭</span><h2>A review that knows what matters to you</h2><p>Set your goals and cash buffer below, then run your first review. You can also start with the calculated checks and refine your brief later.</p></section>}
    <Brief initial={data.settings} onSaved={settings => setData(current => current ? { ...current, settings } : current)} />
  </div>
}

function Finding({ finding: f, onSaved }: { finding: AdvisorFinding; onSaved: (v: AdvisorFeedback) => void }) {
  const [answer, setAnswer] = useState(f.answer)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save(value: AdvisorFeedback) {
    setBusy(true); setError('')
    try { onSaved(await advisorApi.feedback(f.topic, value)) }
    catch (e) { setError(message(e)) }
    finally { setBusy(false) }
  }
  return <article className={`card advisor-finding ${f.priority}`}>
    <div className="advisor-finding-meta"><span className="advisor-badge">{f.priority === 'attention' ? 'Needs attention' : f.priority === 'review' ? 'Worth reviewing' : 'For context'}</span><span className="muted small">{f.kind}</span>{f.feedback !== 'new' && <span className="muted small">· {f.feedback === 'known' ? 'already known' : f.feedback}</span>}</div>
    <h2>{f.title}</h2><p>{f.observation}</p>
    {f.suggestion && <p className="advisor-next"><strong>A next step</strong>{f.suggestion}</p>}
    {f.caveats && <p className="muted small">{f.caveats}</p>}
    <details className="advisor-evidence"><summary>Supporting evidence · {f.evidence.length}</summary>{f.evidence.map(e => <div key={e.ref}><p><Link to={e.snapshot.href}>{e.snapshot.title} →</Link></p><p>{e.explanation}</p><details><summary>Recorded facts</summary><pre>{JSON.stringify(e.snapshot.facts, null, 2)}</pre></details></div>)}</details>
    <div className="advisor-feedback" role="group" aria-label="Finding feedback">{([['useful', 'Useful'], ['known', 'Already know'], ['dismissed', 'Dismiss'], ['incorrect', 'Incorrect']] as const).map(([value, label]) => <button className="btn soft" key={value} disabled={busy} aria-pressed={f.feedback === value} onClick={() => save({ feedback: f.feedback === value ? 'new' : value, answer })}>{label}</button>)}</div>
    <details className="advisor-answer"><summary>{f.answer ? 'Your saved context' : 'Add context or a correction'}</summary><form onSubmit={e => { e.preventDefault(); save({ feedback: f.feedback, answer }) }}><label className="field"><span>Remember this for future reviews</span><textarea rows={3} maxLength={4000} value={answer} onChange={e => setAnswer(e.target.value)} /></label><button className="btn soft" disabled={busy}>Save context</button></form></details>
    {error && <p role="alert" className="bad">{error}</p>}
  </article>
}

function Brief({ initial, onSaved }: { initial: AdvisorSettingsView; onSaved: (s: AdvisorSettingsView) => void }) {
  const [s, set] = useState(initial.values)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('')
    try { const saved = await advisorApi.save(s); onSaved(saved); set(saved.values); setNotice('Your brief and schedule are saved. They apply to queued and future reviews.') }
    catch (e) { setError(message(e)) }
    finally { setBusy(false) }
  }
  return <section className="card advisor-brief" id="advisor-brief"><h2>Your brief & schedule</h2><p className="muted">Tell the advisor what deserves your attention. You can leave any personal context blank.</p>
    <form onSubmit={submit}><fieldset disabled={busy}>
      <div className="form-grid"><label className="field"><span>Goals & things to watch</span><textarea rows={4} maxLength={4000} value={s.goals} placeholder="What are you working towards? What should the review pay attention to?" onChange={e => set({ ...s, goals: e.target.value })} /></label>
      <label className="field"><span>Upcoming expenses</span><textarea rows={4} maxLength={2000} value={s.upcoming_expenses} placeholder="Known costs and when you expect them" onChange={e => set({ ...s, upcoming_expenses: e.target.value })} /></label></div>
      <label className="field"><span>Time horizon & preferences</span><input maxLength={500} value={s.horizon} placeholder="Your time horizon, constraints, or preferences" onChange={e => set({ ...s, horizon: e.target.value })} /></label>
      <div className="form-grid"><label className="field"><span>Cash buffer target (£ GBP)</span><input type="number" min={0} max={1e10} step="0.01" value={s.cash_buffer_gbp ?? ''} placeholder="Optional" onChange={e => set({ ...s, cash_buffer_gbp: e.target.value === '' ? null : Number(e.target.value) })} /><small>Compared with GBP balances in the accounts you select below.</small></label>
      <label className="field"><span>Direct holding review threshold (%)</span><input type="number" min={5} max={100} step="0.1" value={s.concentration_pct} onChange={e => set({ ...s, concentration_pct: Number(e.target.value) })} /><small>A prompt to review an allocation; a fund can hold many companies.</small></label>
      <label className="field"><span>Weekly spending increase to flag (£ GBP)</span><input type="number" min={0} max={1e9} step="0.01" value={s.spending_change_gbp} onChange={e => set({ ...s, spending_change_gbp: Number(e.target.value) })} /><small>Compared with the prior four-week average, when coverage permits.</small></label></div>
      <fieldset className="advisor-accounts"><legend>Accounts to count towards your cash buffer</legend><p className="muted small">Select accounts whose GBP balances you can use. Investment cash and stablecoins are not selected automatically. Manual values need verification.</p><div>{[...new Set([...initial.accounts, ...s.cash_accounts])].map(name => <label className="check" key={name}><input type="checkbox" checked={s.cash_accounts.includes(name)} onChange={e => set({ ...s, cash_accounts: e.target.checked ? [...s.cash_accounts, name] : s.cash_accounts.filter(n => n !== name) })} />{name}{!initial.accounts.includes(name) ? ' (removed account — uncheck)' : ''}</label>)}</div></fieldset>
      <div className="form-grid"><label className="field"><span>Review schedule</span><select value={s.cadence} onChange={e => set({ ...s, cadence: e.target.value as typeof s.cadence })}><option value="weekly">Weekly</option><option value="daily">Daily</option><option value="manual">Manual only</option></select></label>
      {s.cadence === 'weekly' && <label className="field"><span>Day</span><select value={s.weekday} onChange={e => set({ ...s, weekday: Number(e.target.value) })}>{['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map((d, i) => <option value={i} key={d}>{d}</option>)}</select></label>}
      {s.cadence !== 'manual' && <label className="field"><span>Time (Europe/London)</span><input type="time" required value={s.local_time} onChange={e => set({ ...s, local_time: e.target.value })} /></label>}</div>
      <details className="advisor-model"><summary>Model commentary & data sharing</summary><label className="check"><input type="checkbox" checked={s.use_ai} onChange={e => set({ ...s, use_ai: e.target.checked })} /> Add model commentary to calculated checks</label>
        <p className="muted small">When enabled and configured, a bounded summary of balances, holdings, spending categories, recurring merchant names, your brief and feedback is sent through OpenRouter. Account credentials, wallet addresses, bank IDs and individual payment descriptions are excluded. Requests require providers advertising zero data retention and disallow data collection. Review inputs and evidence are saved with your local app data.</p>
        <p className="muted small">{initial.configured ? 'A server-side provider key is configured.' : 'Calculated reviews are ready. To add commentary, set OPENROUTER_API_KEY in the server environment and restart the app, or in the local project’s .env file.'}</p>
        <div className="form-grid"><label className="field"><span>OpenRouter model</span><input required maxLength={150} value={s.model} onChange={e => set({ ...s, model: e.target.value })} /></label><label className="field"><span>Maximum output tokens per review</span><input type="number" min={1000} max={8000} step={100} value={s.max_output_tokens} onChange={e => set({ ...s, max_output_tokens: Number(e.target.value) })} /></label></div>
        <p className="muted small">One model request per review, without automatic retries. Token limits bound request size, not its exact price. There is no external news research in this version.</p>
      </details>
      <div className="advisor-save"><button className="btn primary" disabled={busy}>{busy ? 'Saving…' : 'Save brief & schedule'}</button><span role="status" className="muted small">{notice}</span></div>
      {error && <p role="alert" className="bad">{error}</p>}
    </fieldset></form>
  </section>
}
