import { useState } from 'react'
import { spendingApi, type SpendingReport, type StatementPreview } from '../api'
import { useMoney } from '../Currency'

const errorMessage = (e: unknown) => e instanceof Error ? e.message : String(e)
const dateLabel = (d: string) => new Date(d + 'T12:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

// Read the first CSV record, including escaped quotes and quoted delimiters.
function csvHeaders(text: string) {
  const line = text.replace(/^\uFEFF/, '').split(/\r?\n/)[0] ?? ''
  let delimiter = ','
  let best = 0
  for (const d of [',', ';', '\t']) {
    let quoted = false, count = 0
    for (const c of line) { if (c === '"') quoted = !quoted; else if (c === d && !quoted) count++ }
    if (count > best) { best = count; delimiter = d }
  }
  const headers: string[] = []
  let quoted = false, cell = ''
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (c === '"') {
      if (quoted && line[i + 1] === '"') { cell += '"'; i++ } else quoted = !quoted
    } else if (c === delimiter && !quoted) { headers.push(cell); cell = '' } else cell += c
  }
  headers.push(cell)
  return headers
}

export function StatementImport({ accounts, onImported }: { accounts: SpendingReport['accounts']; onImported: () => void }) {
  const { moneyExact: money, hidden } = useMoney()
  const choices = accounts.filter(a => a.type !== 'monzo' && a.type !== 'lunchflow')
  const [account, setAccount] = useState(choices[0]?.name ?? '')
  const [text, setText] = useState('')
  const [headers, setHeaders] = useState<string[]>([])
  const [mapping, setMapping] = useState<Record<string, string | boolean>>({})
  const [preview, setPreview] = useState<StatementPreview | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const loadFile = async (file?: File) => {
    if (!file) return
    setError(''); setPreview(null)
    if (file.size > 5_000_000) { setError('Choose a CSV under 5 MB.'); return }
    try {
      const value = await file.text()
      const cols = csvHeaders(value)
      const find = (pattern: RegExp) => cols.find(c => pattern.test(c.trim())) ?? ''
      setText(value); setHeaders(cols)
      setMapping({ date: find(/^(transaction )?date$/i), description: find(/^(description|details|transaction description|merchant)$/i),
        amount: find(/^(amount|transaction amount)$/i), debit: find(/^(debit|money out|paid out|withdrawal(s)?)$/i),
        credit: find(/^(credit|money in|paid in|deposit(s)?)$/i), id: find(/^(transaction id|id)$/i), invert: false })
    } catch (e) { setError(errorMessage(e)) }
  }
  const submit = async (commit: boolean) => {
    setBusy(true); setError('')
    try {
      const result = await spendingApi.import(account, text, mapping, commit)
      setPreview(result)
      if (commit) onImported()
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return <section className="statement-import" aria-label="Import bank statement">
    <h3>Import a statement</h3>
    <p className="muted">Choose a GBP CSV with a header row. Dates can use DD/MM/YYYY or YYYY-MM-DD. Preview the amounts before importing.</p>
    {!choices.length ? <p className="empty">Add a manual cash account in Settings first. Connected banks use automatic syncing.</p> : <>
      <div className="spending-controls">
        <label>Account<select value={account} disabled={busy} onChange={e => { setAccount(e.target.value); setPreview(null) }}>{choices.map(a => <option key={a.name}>{a.name}</option>)}</select></label>
        <label>Statement CSV<input type="file" accept=".csv,text/csv,text/plain" disabled={busy} onChange={e => void loadFile(e.target.files?.[0])} /></label>
      </div>
      {headers.length > 0 && <>
        <div className="import-columns">{[['date', 'Date'], ['description', 'Description / merchant'], ['amount', 'Signed amount'], ['debit', 'Money out'], ['credit', 'Money in'], ['id', 'Unique transaction ID (optional)']].map(([key, label]) => <label key={key}>{label}<select disabled={busy} value={String(mapping[key] ?? '')} onChange={e => { setMapping({ ...mapping, [key]: e.target.value }); setPreview(null) }}><option value="">Choose column…</option>{headers.map((h,i) => <option key={i} value={h}>{h}</option>)}</select></label>)}</div>
        <p className="small muted">Use a signed amount column (negative = money out), or leave it blank and choose both money out and money in.</p>
        <label className="spending-check"><input type="checkbox" disabled={busy} checked={!!mapping.invert} onChange={e => { setMapping({ ...mapping, invert: e.target.checked }); setPreview(null) }} /> Reverse amount signs</label>
        <button className="btn primary" disabled={busy} onClick={() => void submit(false)}>{busy ? 'Reading…' : 'Preview statement'}</button>
      </>}
    </>}
    {error && <p className="banner bad" role="alert">{error}</p>}
    {preview && <div className="import-preview">
      <p><b>{preview.new_count} new</b> transactions · {preview.duplicates} already imported · {dateLabel(preview.first_date)} – {dateLabel(preview.last_date)}</p>
      <div className="spending-table-wrap"><table className="spending-table"><thead><tr><th>Date</th><th>Description</th><th>Amount</th></tr></thead><tbody>{preview.preview.map(r => <tr key={r.id}><td>{dateLabel(r.date)}</td><td>{hidden ? '••••' : r.description}</td><td>{money(r.amount / 100)}</td></tr>)}</tbody></table></div>
      <p className="small muted">Repeated imports are deduplicated. A unique bank transaction ID gives the best results; without one, identical same-day payments in partial overlapping files may need review. Positive entries start as income; mark refunds and transfers after import.</p>
      {preview.committed ? <p className="banner">✓ Statement imported.</p> : <button className="btn primary" disabled={busy || !preview.new_count} onClick={() => void submit(true)}>{busy ? 'Importing…' : `Import ${preview.new_count} transactions`}</button>}
    </div>}
  </section>
}

