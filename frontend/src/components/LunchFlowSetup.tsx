import { useEffect, useRef, useState } from 'react'
import { spendingApi, type LunchFlowAccount, type LunchFlowMapping } from '../api'
import { useAsync } from '../hooks'

const message = (error: unknown) => error instanceof Error ? error.message : String(error)

export function LunchFlowSetup({ onSaved }: { onSaved: () => void }) {
  const { data, error, loading, reload } = useAsync(async () => {
    const settings = await spendingApi.lunchflow()
    try {
      const accounts = await spendingApi.lunchflowAccounts()
      return { settings, accounts, discoveryError: '' }
    } catch (error) {
      return { settings, accounts: [] as LunchFlowAccount[], discoveryError: message(error) }
    }
  }, [])
  const [mappings, setMappings] = useState<Record<string, LunchFlowMapping>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const initialised = useRef(false)
  useEffect(() => {
    if (data && !initialised.current) {
      setMappings(Object.fromEntries(data.settings.bindings.filter(b => b.enabled).map(b => [b.id, b])))
      initialised.current = true
    }
  }, [data])

  const update = (id: string, values: Partial<LunchFlowMapping>) => {
    setSaveError('')
    setMappings(previous => ({ ...previous, [id]: { ...previous[id], ...values } }))
  }
  const save = async () => {
    setSaving(true); setSaveError('')
    try { await spendingApi.saveLunchflow(Object.values(mappings)); onSaved() }
    catch (error) { setSaveError(message(error)) }
    finally { setSaving(false) }
  }
  const accounts = [...(data?.accounts ?? [])]
  data?.settings.bindings.forEach(b => {
    if (!accounts.some(a => a.id === b.id)) accounts.push({ id: b.id, name: b.account, institution: b.institution, currency: 'GBP', status: 'UNAVAILABLE' })
  })
  return <section className="bank-settings" aria-label="Lunch Flow accounts" aria-busy={loading}>
    <div className="bank-settings-heading"><div><h3>Lunch Flow</h3><p className="muted small">Choose which bank accounts appear in Spending.</p></div><button className="btn ghost" disabled={loading || saving} onClick={reload}><span aria-hidden="true">↻</span> Refresh</button></div>
    {loading && <p className="empty" role="status">Loading connected accounts…</p>}
    {!loading && (error || data?.discoveryError) && <div className="bank-settings-error" role="alert">
      <b>{data && !data.settings.configured ? 'Add your API key to connect' : 'Couldn’t load your bank accounts'}</b>
      <p className="small">{data && !data.settings.configured ? <>Set <code>LUNCHFLOW_API_KEY</code> in the app’s <code>.env</code> file, then retry. No restart needed.</> : error || data?.discoveryError}</p>
      <button className="btn" onClick={reload}>Retry connection</button>
    </div>}
    {!loading && data && !data.discoveryError && !accounts.length && <p className="empty">No accounts shared yet. Enable Santander and American Express under Account Access in your Lunch Flow API destination, then refresh.</p>}
    {!loading && accounts.map(a => {
      const selected = mappings[a.id]
      const saved = data?.settings.bindings.find(b => b.id === a.id)
      const available = (!a.currency || a.currency === 'GBP') && a.status === 'ACTIVE'
      const title = a.institution || a.name
      const name = saved?.account ?? data?.settings.choices.find(c => [a.institution.toLowerCase(), a.name.toLowerCase()].includes(c.name.toLowerCase()))?.name ?? (a.institution ? `${a.institution} · ${a.name}` : a.name)
      const csvStart = data?.settings.choices.find(c => c.name === selected?.account)?.start_date
      return <article className={`bank-connection ${selected ? 'selected' : ''}`} key={a.id}>
        <label className="bank-connection-toggle"><span className="bank-connection-copy"><strong>{title}</strong><span className="small muted">{a.institution ? `${a.name} · ` : ''}{a.currency || 'Currency checked on import'}{!available ? ' · Unavailable' : selected ? ' · Sync enabled' : ' · Not syncing'}</span></span><input type="checkbox" aria-label={`Sync ${title} ${a.name}`} checked={!!selected} disabled={saving || !!data?.discoveryError || (!available && !selected)} onChange={e => {
          setSaveError('')
          if (e.target.checked) update(a.id, { id: a.id, account: name, start_date: saved?.start_date ?? data?.settings.choices.find(c => c.name === name)?.start_date ?? '' })
          else setMappings(previous => Object.fromEntries(Object.entries(previous).filter(([id]) => id !== a.id)))
        }} /></label>
        {selected && <details className="bank-import-options"><summary>Import options</summary><div className="form-grid">
          <label className="field"><span>Account name in this app</span><input list="lunchflow-account-names" value={selected.account} readOnly={!!saved} disabled={saving} maxLength={100} onChange={e => update(a.id, { account: e.target.value, start_date: data?.settings.choices.find(c => c.name === e.target.value)?.start_date ?? '' })} /><small>{saved ? 'Linked to this account.' : 'Choose an existing account or enter a new name.'}</small></label>
          <label className="field"><span>History starts</span><input type="date" value={selected.start_date ?? ''} min={csvStart || undefined} disabled={saving} onChange={e => update(a.id, { start_date: e.target.value })} /><small>{csvStart ? `After existing statement history (${csvStart} onwards).` : 'Leave blank for all available transactions.'}</small></label>
        </div></details>}
      </article>
    })}
    <datalist id="lunchflow-account-names">{data?.settings.choices.map(c => <option key={c.name} value={c.name} />)}</datalist>
    {!loading && data && !data.discoveryError && <p className="small muted">Selected accounts sync hourly. Turning one off keeps its transaction history.</p>}
    {saveError && <p className="banner bad" role="alert">{saveError}</p>}
    <div className="form-actions"><span className="small muted">{Object.keys(mappings).length} accounts selected</span><span className="spacer" /><button className="btn primary" disabled={loading || saving || !data || !!error || !!data.discoveryError} onClick={() => void save()}>{saving ? 'Saving…' : 'Save changes'}</button></div>
  </section>
}
