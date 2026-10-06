import { useMoney } from '../Currency'
import { Link } from 'react-router'
import { Popover } from './Popover'
import { useEffect, useRef, useState } from 'react'
import { api, type Quote } from '../api'
import { KIND_EMOJI } from '../colors'
import { flag } from '../flags'
import { useStoredState } from '../hooks'
import { pct, units } from '../format'
import type { AddedHolding, Row, Scenario } from '../scenario'

type Props = {
  accountName: string
  rows: Row[]
  setScenario: (update: (s: Scenario) => Scenario) => void
  editing: boolean
  canAdd: boolean
  onDetails: (row: Row) => void
  dustToggle?: boolean
}

const DUST_GBP = 1

/** Worth less than £1 and not something you've touched in the sandbox. Unpriced tokens aren't dust - they're unknown. */
const isDust = (r: Row) => !r.added && !r.edited && !r.unpriced && Math.abs(r.actualValue) < DUST_GBP

export function HoldingsTable({ accountName, rows, setScenario, editing, canAdd, onDetails, dustToggle = false }: Props) {
  const { money, moneyExact, signedMoney, symbol, currency, toDisplay, toGBP } = useMoney()
  const [hideDust, setHideDust] = useStoredState('networth:hide-dust', true)
  const visibleTotal = rows.filter(r => !r.hidden).reduce((s, r) => s + r.value, 0)
  const dustCount = dustToggle ? rows.filter(isDust).length : 0
  const listed = dustToggle && hideDust ? rows.filter(r => !isDust(r)) : rows
  const sorted = [...listed].sort((a, b) => Number(a.added) - Number(b.added) || b.actualValue - a.actualValue)

  const toggle = (asset: string) =>
    setScenario(s => ({
      ...s,
      hidden: s.hidden.includes(asset) ? s.hidden.filter(a => a !== asset) : [...s.hidden, asset],
    }))

  const setQuantity = (row: Row, quantity: number) => {
    if (!Number.isFinite(quantity) || quantity < 0) return
    setScenario(s => {
      if (row.added) {
        return { ...s, added: s.added.map(a => (a.asset === row.asset ? { ...a, quantity } : a)) }
      }
      const quantities = { ...s.quantities }
      if (Math.abs(quantity - row.actualQuantity) < 1e-9) delete quantities[row.asset]
      else quantities[row.asset] = quantity
      return { ...s, quantities }
    })
  }

  const reset = (row: Row) =>
    setScenario(s =>
      row.added
        ? { ...s, added: s.added.filter(a => a.asset !== row.asset), hidden: s.hidden.filter(a => a !== row.asset) }
        : { ...s, quantities: Object.fromEntries(Object.entries(s.quantities).filter(([a]) => a !== row.asset)) },
    )

  return (
    <section className="card holdings">
      <header className="card-head">
        <h3><span className="emoji">🧾</span> Holdings</h3>
        <span className="muted small">
          {editing ? 'Type a new value or number of units - the other one follows the current price' : 'Flip the switch to leave a holding out of every number on this page'}
        </span>
      </header>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th aria-label="Included" />
              <th>Holding</th>
              <th className="num">Units</th>
              <th className="num">Price</th>
              <th className="num">Value</th>
              <th className="num">Share</th>
              {editing && <th aria-label="Reset" />}
            </tr>
          </thead>
          <tbody>
            {sorted.map(row => {
              const c = row.classification
              const countries = c ? Object.keys(c.countries).filter(k => k !== 'Cash') : []
              const diff = row.value - row.actualValue
              return (
                <tr key={row.asset} className={`${row.hidden ? 'is-hidden' : ''} ${row.edited ? 'is-edited' : ''}`}>
                  <td>
                    <label className="switch" title={row.hidden ? 'Include' : 'Leave out'}>
                      <input type="checkbox" checked={!row.hidden} disabled={row.unpriced} onChange={() => toggle(row.asset)} />
                      <span />
                    </label>
                  </td>
                  <td>
                    <div className="holding-name">
                      {c?.symbol ? (
                        <button className="ticker link" onClick={() => onDetails(row)} title={`About ${row.name}`}>{row.asset}</button>
                      ) : row.locations?.length ? (
                        <Popover trigger={row.asset} label={`${row.asset} balances and links`}>
                          {row.locations.map((location, i) => <span className="token-location" key={i}>
                            <Link to={`/accounts/${encodeURIComponent(accountName)}/chains/${encodeURIComponent(location.chain)}`}>{location.chain} ↗</Link>
                            <Link to={`/accounts/${encodeURIComponent(accountName)}/wallets/${encodeURIComponent(location.wallet)}`}>
                              {location.wallet.slice(0, 7)}…{location.wallet.slice(-5)} ↗
                            </Link>
                            <span className="muted small">{location.quantity.toLocaleString('en-GB', { maximumFractionDigits: 6 })} {row.asset}{location.name && location.name !== location.chain ? ` · ${location.name}` : ''}</span>
                          </span>)}
                        </Popover>
                      ) : (
                        <span className="ticker">{row.asset === 'GBP' ? '💷 Cash' : row.asset}</span>
                      )}
                      {row.unpriced && <Popover trigger="⚠" label={`${row.asset} unpriced`} warning hover>
                        {row.asset === 'DFX-CLAIM'
                          ? 'Unclaimed Drift recovery allocation. No reliable redemption value is available; excluded from net worth.'
                          : 'No reliable price is available for this token; excluded from net worth.'}
                      </Popover>}
                      {row.added && <span className="badge new">sandbox</span>}
                      {c && c.kind !== 'cash' && (
                        <span className="badge" title={c.source ? `Exposure from ${c.source}` : undefined}>
                          {KIND_EMOJI[c.kind]} {c.kind}
                        </span>
                      )}
                      {countries.length > 0 && (
                        <span className="flags" title={countries.join(', ')}>
                          {countries.length === 1 ? flag(countries[0]) : `${countries.slice(0, 3).map(flag).join('')}${countries.length > 3 ? '…' : ''}`}
                        </span>
                      )}
                    </div>
                    <div className="muted small truncate">{row.asset === 'GBP' ? 'Uninvested' : row.name}</div>
                    {c?.error && <div className="error-text small">Couldn't look up exposure</div>}
                  </td>
                  <td className="num">
                    {editing && !row.unpriced && row.asset !== 'GBP' ? (
                      <NumberInput value={row.quantity} onCommit={q => setQuantity(row, q)} label={`${row.asset} units`} />
                    ) : (
                      row.unpriced ? row.quantity.toLocaleString('en-GB', { maximumFractionDigits: 6 }) : units(row.quantity)
                    )}
                    {row.edited && !row.added && <div className="was">was {units(row.actualQuantity)}</div>}
                  </td>
                  <td className="num muted">{row.unpriced || row.asset === 'GBP' ? '—' : moneyExact(row.price)}</td>
                  <td className="num strong">
                    {row.unpriced ? '—' : editing ? (
                      <NumberInput key={currency} value={toDisplay(row.value)} onCommit={v => row.price && setQuantity(row, toGBP(v) / row.price)} label={`${row.asset} value in ${currency}`} prefix={symbol} />
                    ) : (
                      money(row.value)
                    )}
                    {row.edited && <div className={`was ${diff >= 0 ? 'up' : 'down'}`}>{signedMoney(diff)}</div>}
                  </td>
                  <td className="num">
                    {row.unpriced ? <span className="muted">—</span> : row.hidden ? <span className="muted">hidden</span> : (
                      <div className="share">
                        <span>{pct(visibleTotal ? row.value / visibleTotal : 0)}</span>
                        <span className="share-bar"><span style={{ width: `${visibleTotal ? (row.value / visibleTotal) * 100 : 0}%` }} /></span>
                      </div>
                    )}
                  </td>
                  {editing && (
                    <td>
                      {(row.edited || row.added) && (
                        <button className="icon-btn" onClick={() => reset(row)} title={row.added ? 'Remove' : 'Undo change'}>
                          {row.added ? '✕' : '↺'}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {dustCount > 0 && (
        <div className="dust-toggle">
          <label className="check">
            <input type="checkbox" checked={hideDust} onChange={e => setHideDust(e.target.checked)} />
            <span>Hide dust <small>{dustCount} under {money(DUST_GBP)}</small></span>
          </label>
        </div>
      )}
      {editing && canAdd && <AddHolding existing={rows.map(r => r.asset)} setScenario={setScenario} />}
    </section>
  )
}

function NumberInput({ value, onCommit, label, prefix }: { value: number; onCommit: (v: number) => void; label: string; prefix?: string }) {
  const [draft, setDraft] = useState<string | null>(null)
  const shown = draft ?? (Math.round(value * 100) / 100).toString()
  const commit = () => {
    if (draft !== null) {
      const v = parseFloat(draft.replace(/[$£,\s]/g, ''))
      if (Number.isFinite(v)) onCommit(v)
    }
    setDraft(null)
  }
  return (
    <span className="num-input">
      {prefix && <span>{prefix}</span>}
      <input
        aria-label={label}
        inputMode="decimal"
        value={shown}
        onChange={e => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={e => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
          if (e.key === 'Escape') setDraft(null)
        }}
      />
    </span>
  )
}

const DEFAULT_AMOUNT = '1000'

type Lookup = { ticker: string; busy: boolean; quote?: Quote; error?: string }

/** Looks the ticker up as soon as you leave its box, so the price is there by the time you press Add. */
function AddHolding({ existing, setScenario }: { existing: string[]; setScenario: Props['setScenario'] }) {
  const { moneyExact, symbol, currency, factor, toDisplay, toGBP } = useMoney()
  const [ticker, setTicker] = useState('')
  const [amount, setAmount] = useState(() => String(toDisplay(Number(DEFAULT_AMOUNT))))
  const previousFactor = useRef(factor)
  useEffect(() => {
    if (factor !== previousFactor.current) {
      const oldFactor = previousFactor.current
      setAmount(amount => String(Number(amount.replace(/[$£,\s]/g, '')) / oldFactor * factor))
      previousFactor.current = factor
    }
  }, [factor])
  const [lookup, setLookup] = useState<Lookup | null>(null)
  const pending = useRef<{ ticker: string; promise: Promise<Quote> } | null>(null)

  const find = (raw: string): Promise<Quote> | null => {
    const t = raw.trim().toUpperCase()
    if (!t) {
      setLookup(null)
      return null
    }
    if (pending.current?.ticker === t) return pending.current.promise
    if (existing.includes(t)) {
      setLookup({ ticker: t, busy: false, error: `${t} is already in the list - edit it above instead` })
      return null
    }
    const promise = api.quote(t).then(q => {
      if (!q.price_gbp) throw new Error(`No GBP price for ${t}`)
      return q
    })
    pending.current = { ticker: t, promise }
    setLookup({ ticker: t, busy: true })
    promise.then(
      quote => pending.current?.promise === promise && setLookup({ ticker: t, busy: false, quote }),
      err => {
        if (pending.current?.promise !== promise) return
        pending.current = null  // so leaving the box again retries
        setLookup({ ticker: t, busy: false, error: err instanceof Error ? err.message : String(err) })
      },
    )
    return promise
  }

  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    const value = toGBP(parseFloat(amount.replace(/[$£,\s]/g, '')))
    if (!Number.isFinite(value) || value <= 0) return
    const found = find(ticker)
    if (!found) return
    let q: Quote
    try {
      q = await found
    } catch {
      return  // shown by the lookup
    }
    const holding: AddedHolding = { asset: q.asset, name: q.name, price: q.price_gbp!, quantity: value / q.price_gbp!, classification: q }
    setScenario(s => ({ ...s, added: [...s.added, holding] }))
    setTicker('')
    setAmount(String(toDisplay(Number(DEFAULT_AMOUNT))))
    setLookup(null)
    pending.current = null
  }

  const current = lookup && lookup.ticker === ticker.trim().toUpperCase() ? lookup : null
  const value = toGBP(parseFloat(amount.replace(/[$£,\s]/g, '')))

  return (
    <form className="add-holding" onSubmit={add}>
      <span className="add-title">✨ Add a holding</span>
      <input
        placeholder="Ticker, e.g. VWRL or SHEL.L"
        value={ticker}
        onChange={e => setTicker(e.target.value)}
        onBlur={() => find(ticker)}
        aria-label="Ticker"
      />
      <span className="num-input wide">
        <span>{symbol}</span>
        <input value={amount} onChange={e => setAmount(e.target.value)} inputMode="decimal" aria-label={`Amount in ${currency === "USD" ? "dollars" : "pounds"}`} />
      </span>
      <button className="btn primary" disabled={!ticker.trim() || !!current?.busy || !!current?.error}>
        {current?.busy ? 'Looking up…' : 'Add'}
      </button>
      {current?.quote && (
        <span className="lookup small">
          ✓ <b>{current.quote.name}</b> · {moneyExact(current.quote.price_gbp!)}
          {Number.isFinite(value) && value > 0 && <span className="muted"> · {units(value / current.quote.price_gbp!)} units</span>}
        </span>
      )}
      {current?.error && <span className="error-text small">{current.error}</span>}
      <span className="muted small hint">US listings win for dual-listed tickers - add <code>.L</code> for London.</span>
    </form>
  )
}
