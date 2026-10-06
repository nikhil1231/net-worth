import { useMoney } from '../Currency'
import { type FormEvent, useState } from 'react'
import { type AccountConfig, type ConfigData, type Summary, api } from '../api'
import { categoryStyle } from '../colors'
import { AccountForm } from '../components/AccountForm'

import { useAsync } from '../hooks'

type Props = { summary: Summary; onSummary: (s: Summary) => void }

const TYPE_EMOJI: Record<string, string> = {
  bitcoin: '₿', evm: 'Ξ', solana: '◎', exchange: '🏦', manual: '✍️', hl: '📈', monzo: '💳',
}
const DEFAULT_CATEGORY: Record<string, string> = {
  bitcoin: 'crypto', evm: 'crypto', solana: 'crypto', exchange: 'crypto', hl: 'investments', monzo: 'cash', manual: 'cash',
}
const QUICK_ADD = ['bitcoin', 'evm', 'solana', 'exchange', 'manual']
const STANDARD_CATEGORIES = ['investments', 'crypto', 'cash', 'property', 'pension']

/** What's left after a save: the account is fetched straight away so mistakes show up here. */
type Check = { state: 'fetching' } | { state: 'ok'; value: number } | { state: 'bad'; text: string }

function describe(a: AccountConfig, config: ConfigData, nativeMoney: (value: number, currency: string) => string) {
  const bits = [config.connectors[a.type]?.label ?? a.type]
  const { addresses, exchange, value, chains } = a.params
  if (Array.isArray(addresses)) bits.push(`${addresses.length} address${addresses.length === 1 ? '' : 'es'}`)
  if (Array.isArray(chains)) bits.push(`${chains.length} chain${chains.length === 1 ? '' : 's'}`)
  if (typeof exchange === 'string') bits.push(exchange)
  if (typeof value === 'number') bits.push(nativeMoney(value, String(a.params.currency ?? 'GBP')))
  bits.push(`every ${a.interval ?? config.settings.default_interval} min`)
  return bits.join(' · ')
}

export function Settings({ summary, onSummary }: Props) {
  const { money, nativeMoney } = useMoney()
  const { data: config, error, setData: setConfig } = useAsync(api.config, [])
  const [editing, setEditing] = useState<{ original: string | null; initial: AccountConfig; id: number } | null>(null)
  const [checks, setChecks] = useState<Record<string, Check>>({})

  if (error) return <div className="page"><div className="banner bad"><span>😬</span><div>Couldn't load the config: {error}</div></div></div>
  if (!config) return <div className="page"><div className="loading-card">⚙️ Reading accounts.yaml…</div></div>

  const live = new Map(summary.accounts.map(a => [a.name, a]))
  const categories = [...new Set([...STANDARD_CATEGORIES, ...config.accounts.map(a => a.category)])]
  const grouped = new Map<string, AccountConfig[]>()
  for (const a of config.accounts) grouped.set(a.category, [...(grouped.get(a.category) ?? []), a])
  const categoryIndex = (c: string) => [...grouped.keys()].indexOf(c)

  const startAdd = (type: string) => {
    const label = config.connectors[type]?.label.replace(/\s*\(.*\)$/, '') ?? ''
    const taken = new Set(config.accounts.map(a => a.name))
    let name = label
    for (let i = 2; taken.has(name); i++) name = `${label} ${i}`
    setEditing({ original: null, initial: { name, type, category: DEFAULT_CATEGORY[type] ?? 'crypto', interval: null, params: {} }, id: Date.now() })
  }

  const check = async (name: string) => {
    setChecks(c => ({ ...c, [name]: { state: 'fetching' } }))
    try {
      const s = await api.refresh(name)
      onSummary(s)
      const a = s.accounts.find(x => x.name === name)
      setChecks(c => ({
        ...c,
        [name]: a?.last_error ? { state: 'bad', text: a.last_error } : { state: 'ok', value: a?.value ?? 0 },
      }))
    } catch (e) {
      setChecks(c => ({ ...c, [name]: { state: 'bad', text: e instanceof Error ? e.message : String(e) } }))
    }
  }

  const save = async (account: AccountConfig) => {
    setConfig(await api.saveAccount(editing!.original, account))
    setEditing(null)
    check(account.name)
  }

  const remove = async () => {
    setConfig(await api.deleteAccount(editing!.original!))
    setEditing(null)
    onSummary(await api.summary())
  }

  return (
    <div className="page">
      <section className="settings-head">
        <h1>⚙️ Settings</h1>
        <p className="muted">Changes are written to <code>{config.path}</code> and take effect straight away - no restart needed.</p>
      </section>

      {!config.writable && (
        <div className="banner warn">
          <span>🔒</span>
          <div><b>Read-only.</b> The server can't write to <code>{config.path}</code>, so this page is view-only. In Docker, drop <code>:ro</code> from its volume mount.</div>
        </div>
      )}

      <section className="card">
        <div className="card-head wrap">
          <h3><span className="emoji">🗂️</span> Accounts</h3>
          {config.writable && (
            <div className="quick-add">
              <span className="muted small">Add</span>
              {QUICK_ADD.filter(t => config.connectors[t]).map(t => (
                <button key={t} className="btn soft" onClick={() => startAdd(t)}>
                  <span>{TYPE_EMOJI[t]}</span> {config.connectors[t].label.replace(/\s*\(.*\)$/, '')}
                </button>
              ))}
              <button className="btn primary" onClick={() => startAdd(Object.keys(config.connectors).find(t => !QUICK_ADD.includes(t)) ?? 'manual')}>＋ Other…</button>
            </div>
          )}
        </div>

        {config.accounts.length === 0 && <p className="empty">No accounts yet - add one above 👆</p>}
        {[...grouped].map(([category, accounts]) => {
          const style = categoryStyle(category, categoryIndex(category))
          return (
            <div key={category} className="config-group">
              <h4>{style.emoji} {category}</h4>
              <ul className="config-list">
                {accounts.map(a => {
                  const current = live.get(a.name)
                  const c = checks[a.name]
                  return (
                    <li key={a.name} style={{ ['--c' as string]: style.color }}>
                      <button className="config-row" onClick={() => setEditing({ original: a.name, initial: a, id: Date.now() })}>
                        <span className="config-icon">{TYPE_EMOJI[a.type] ?? '🔌'}</span>
                        <span className="config-main">
                          <span className="config-name">{a.name}</span>
                          <span className="muted small truncate">{describe(a, config, nativeMoney)}</span>
                        </span>
                        <span className="config-status">
                          {c?.state === 'fetching' && <span className="status"><span className="spin">🔄</span> checking…</span>}
                          {c?.state === 'ok' && <span className="status ok">✓ {money(c.value)}</span>}
                          {c?.state === 'bad' && <span className="status bad" title={c.text}>⚠️ {c.text.slice(0, 60)}</span>}
                          {!c && current && (current.last_error
                            ? <span className="status bad" title={current.last_error}>⚠️ failing</span>
                            : <span className="muted small">{money(current.value)}</span>)}
                        </span>
                        <span className="chevron">›</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          )
        })}
      </section>

      <ScheduleCard config={config} onSaved={setConfig} />

      {editing && (
        <AccountForm
          key={editing.id}
          open
          original={editing.original}
          initial={editing.initial}
          config={config}
          categories={categories}
          onClose={() => setEditing(null)}
          onSave={save}
          onDelete={remove}
        />
      )}
    </div>
  )
}

function ScheduleCard({ config, onSaved }: { config: ConfigData; onSaved: (c: ConfigData) => void }) {
  const [tick, setTick] = useState(String(config.settings.tick_minutes))
  const [interval, setIntervalText] = useState(String(config.settings.default_interval))
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const dirty = tick !== String(config.settings.tick_minutes) || interval !== String(config.settings.default_interval)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setStatus(null)
    try {
      onSaved(await api.saveSettings({ tick_minutes: Number(tick), default_interval: Number(interval) }))
      setStatus({ ok: true, text: 'Saved ✓' })
    } catch (err) {
      setStatus({ ok: false, text: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <div className="card-head"><h3><span className="emoji">⏱️</span> Schedule</h3></div>
      <form onSubmit={submit}>
        <fieldset className="form" disabled={!config.writable || busy}>
          <div className="form-grid">
            <label className="field">
              <span>Re-price every (minutes)</span>
              <input type="number" min={1} step={1} required value={tick} onChange={e => setTick(e.target.value)} />
              <small>How often the scheduler wakes up, values everything and saves a snapshot.</small>
            </label>
            <label className="field">
              <span>Default fetch interval (minutes)</span>
              <input type="number" min={1} step={1} required value={interval} onChange={e => setIntervalText(e.target.value)} />
              <small>For accounts without their own interval.</small>
            </label>
          </div>
          <div className="form-actions">
            {status && <span className={status.ok ? 'up small strong' : 'error-text small'}>{status.text}</span>}
            <span className="spacer" />
            <button type="submit" className="btn primary" disabled={!dirty || busy}>{busy ? 'Saving…' : 'Save schedule'}</button>
          </div>
        </fieldset>
      </form>
    </section>
  )
}
