import { type FormEvent, useState } from 'react'
import YAML from 'yaml'
import { type AccountConfig, type ConfigData, type FieldSpec, SECRET_MASK } from '../api'
import { CloseButton, Modal } from './Modal'

type Props = {
  open: boolean
  original: string | null // null when adding
  initial: AccountConfig
  config: ConfigData
  categories: string[]
  onClose: () => void
  onSave: (account: AccountConfig) => Promise<void>
  onDelete: () => Promise<void>
}

/** Form values are strings (bools for checkboxes), keyed by param. Params without a field go in `other` as YAML. */
type Values = Record<string, string | boolean>

function toValues(fields: FieldSpec[], params: Record<string, unknown>): [Values, string] {
  const values: Values = {}
  for (const f of fields) {
    const v = params[f.key]
    if (f.kind === 'bool') values[f.key] = typeof v === 'boolean' ? v : Boolean(f.default)
    else if (v == null) values[f.key] = ''
    else if (f.kind === 'list') values[f.key] = Array.isArray(v) ? v.join('\n') : String(v)
    else if (f.kind === 'yaml') values[f.key] = YAML.stringify(v).trimEnd()
    else values[f.key] = String(v)
  }
  const keys = new Set(fields.map(f => f.key))
  const rest = Object.fromEntries(Object.entries(params).filter(([k]) => !keys.has(k)))
  return [values, Object.keys(rest).length ? YAML.stringify(rest).trimEnd() : '']
}

function toParams(fields: FieldSpec[], values: Values, other: string): Record<string, unknown> {
  let params: Record<string, unknown> = {}
  if (other.trim()) {
    const parsed = parseYaml('Other params', other)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error('Other params must be key: value lines')
    params = parsed as Record<string, unknown>
  }
  for (const f of fields) {
    const v = values[f.key]
    delete params[f.key]
    if (f.kind === 'bool') {
      if (v !== Boolean(f.default)) params[f.key] = v
      continue
    }
    const text = typeof v === 'string' ? v.trim() : ''
    if (!text) continue
    if (f.kind === 'list') params[f.key] = text.split('\n').map(s => s.trim()).filter(Boolean)
    else if (f.kind === 'yaml') params[f.key] = parseYaml(f.label, text)
    else if (f.kind === 'number') {
      const n = Number(text.replace(/,/g, ''))
      if (Number.isNaN(n)) throw new Error(`${f.label} must be a number`)
      params[f.key] = n
    } else params[f.key] = text
  }
  return params
}

function parseYaml(label: string, text: string): unknown {
  try {
    return YAML.parse(text)
  } catch (e) {
    throw new Error(`${label}: ${e instanceof Error ? e.message.split('\n')[0] : e}`)
  }
}

export function AccountForm({ open, original, initial, config, categories, onClose, onSave, onDelete }: Props) {
  const fieldsOf = (type: string) => config.connectors[type]?.fields ?? []
  const [name, setName] = useState(initial.name)
  const [type, setType] = useState(initial.type)
  const [category, setCategory] = useState(initial.category)
  const [interval, setIntervalText] = useState(initial.interval?.toString() ?? '')
  const [[values, other], setForm] = useState(() => toValues(fieldsOf(initial.type), initial.params))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const fields = fieldsOf(type)
  const readOnly = !config.writable

  const setValue = (key: string, v: string | boolean) => setForm([{ ...values, [key]: v }, other])
  const changeType = (next: string) => {
    // Values are keyed by param, so ones both types share (e.g. addresses) carry over.
    const [fresh] = toValues(fieldsOf(next), {})
    setForm([{ ...fresh, ...Object.fromEntries(Object.entries(values).filter(([k]) => k in fresh)) }, other])
    setType(next)
  }

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    run(async () => {
      const minutes = interval.trim() ? Number(interval) : null
      if (minutes !== null && (!Number.isInteger(minutes) || minutes < 1)) throw new Error('Interval must be a whole number of minutes')
      await onSave({ name: name.trim(), type, category: category.trim(), interval: minutes, params: toParams(fields, values, other) })
    })
  }

  return (
    <Modal open={open} onClose={onClose}>
      <form className="modal-body" onSubmit={submit}>
        <div className="modal-head">
          <div>
            <p className="modal-kicker muted">{original === null ? 'New account' : 'Edit account'}</p>
            <h2>{name || config.connectors[type]?.label || 'Account'}</h2>
          </div>
          <CloseButton onClose={onClose} />
        </div>

        <fieldset className="form" disabled={readOnly || busy}>
          <div className="form-grid">
            <label className="field">
              <span>Name</span>
              <input value={name} onChange={e => setName(e.target.value)} required autoFocus={original === null} />
              {original !== null && name.trim() !== original && <small>History, cookies and tokens move to the new name.</small>}
            </label>
            <label className="field">
              <span>Type</span>
              <select value={type} onChange={e => changeType(e.target.value)}>
                {Object.entries(config.connectors).map(([key, c]) => <option key={key} value={key}>{c.label}</option>)}
              </select>
            </label>
            <label className="field">
              <span>Category</span>
              <input value={category} onChange={e => setCategory(e.target.value)} list="categories" required />
              <datalist id="categories">{categories.map(c => <option key={c} value={c} />)}</datalist>
            </label>
            <label className="field">
              <span>Fetch every (minutes)</span>
              <input type="number" min={1} step={1} value={interval} onChange={e => setIntervalText(e.target.value)}
                placeholder={`${config.settings.default_interval} (default)`} />
            </label>
          </div>

          {fields.length > 0 && <h4>Details</h4>}
          {fields.map(f => <FieldInput key={f.key} field={f} value={values[f.key]} onChange={v => setValue(f.key, v)} />)}

          <details className="field" open={Boolean(other)}>
            <summary>Other params (YAML)</summary>
            <textarea rows={Math.min(12, Math.max(3, other.split('\n').length + 1))} value={other}
              onChange={e => setForm([values, e.target.value])} spellCheck={false} placeholder="key: value" />
            <small>Anything else the connector reads - see its docstring in <code>networth/connectors/{type}.py</code>.</small>
          </details>
        </fieldset>

        {error && <div className="banner bad"><span>😬</span><div>{error}</div></div>}

        <div className="form-actions">
          {original !== null && !readOnly && (
            confirmDelete
              ? <button type="button" className="btn danger" disabled={busy} onClick={() => run(onDelete)}>Really delete {original}?</button>
              : <button type="button" className="btn ghost danger-text" onClick={() => setConfirmDelete(true)}>🗑️ Delete</button>
          )}
          <span className="spacer" />
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          {!readOnly && <button type="submit" className="btn primary" disabled={busy}>{busy ? 'Saving…' : original === null ? 'Add account' : 'Save'}</button>}
        </div>
      </form>
    </Modal>
  )
}

function FieldInput({ field: f, value, onChange }: { field: FieldSpec; value: string | boolean; onChange: (v: string | boolean) => void }) {
  if (f.kind === 'bool') {
    return (
      <label className="check">
        <input type="checkbox" checked={value === true} onChange={e => onChange(e.target.checked)} /> {f.label}
        {f.help && <small className="muted">{f.help}</small>}
      </label>
    )
  }
  const text = typeof value === 'string' ? value : ''
  const multiline = f.kind === 'list' || f.kind === 'yaml'
  const secret = f.kind === 'secret'
  return (
    <label className="field">
      <span>{f.label}{f.required && <b className="req"> *</b>}</span>
      {multiline ? (
        <textarea rows={Math.min(10, Math.max(f.kind === 'yaml' ? 3 : 2, text.split('\n').length + 1))} value={text}
          onChange={e => onChange(e.target.value)} placeholder={f.placeholder ?? (f.kind === 'list' ? 'One per line' : '')}
          spellCheck={false} className="mono" />
      ) : (
        <input
          type={secret && !text.startsWith('${') ? 'password' : 'text'}
          inputMode={f.kind === 'number' ? 'decimal' : undefined}
          value={text}
          onChange={e => onChange(e.target.value)}
          onFocus={e => secret && text === SECRET_MASK && e.target.select()}
          placeholder={f.placeholder ?? undefined}
          autoComplete="off"
          spellCheck={false}
        />
      )}
      {(f.help || secret) && (
        <small>
          {f.help}
          {secret && <>{f.help ? ' · ' : ''}{text === SECRET_MASK ? 'Saved - type to replace. ' : ''}<code>{'${VAR}'}</code> reads it from .env</>}
        </small>
      )}
    </label>
  )
}
