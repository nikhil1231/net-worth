import type { AccountDetail, Classification, HoldingLocation } from './api'

/** Sandbox changes to an account, kept per account in localStorage. */
export type Scenario = {
  hidden: string[]                   // assets left out of every total and chart
  quantities: Record<string, number> // edited quantities of held assets
  added: AddedHolding[]              // holdings added in the sandbox
}

export type AddedHolding = {
  asset: string
  name: string
  price: number
  quantity: number
  classification: Classification
}

export const EMPTY_SCENARIO: Scenario = { hidden: [], quantities: {}, added: [] }

export type Row = {
  asset: string
  name: string
  price: number
  actualQuantity: number
  quantity: number
  actualValue: number
  value: number
  hidden: boolean
  edited: boolean
  added: boolean
  classification?: Classification
  locations?: HoldingLocation[]
  unpriced?: boolean
}

export function buildRows(detail: AccountDetail, scenario: Scenario): Row[] {
  const hidden = new Set(scenario.hidden)
  const held: Row[] = detail.holdings.map(h => {
    const price = h.price ?? (h.quantity ? h.value / h.quantity : 0)
    const quantity = scenario.quantities[h.asset] ?? h.quantity
    return {
      locations: h.locations,
      asset: h.asset,
      name: h.name ?? detail.classifications[h.asset]?.name ?? h.asset,
      price,
      actualQuantity: h.quantity,
      quantity,
      actualValue: h.value,
      value: h.asset in scenario.quantities ? quantity * price : h.value,
      hidden: hidden.has(h.asset),
      edited: h.asset in scenario.quantities && Math.abs(quantity - h.quantity) > 1e-9,
      added: false,
      classification: detail.classifications[h.asset],
    }
  })
  const unpriced: Row[] = detail.unpriced.filter(h => h.quantity !== 0).map(h => ({
    locations: h.locations, asset: h.asset, name: h.name ?? h.asset, price: 0,
    actualQuantity: h.quantity, quantity: h.quantity, actualValue: 0, value: 0,
    hidden: false, edited: false, added: false, unpriced: true,
  }))
  const added: Row[] = scenario.added.map(a => ({
    asset: a.asset,
    name: a.name,
    price: a.price,
    actualQuantity: 0,
    quantity: a.quantity,
    actualValue: 0,
    value: a.quantity * a.price,
    hidden: hidden.has(a.asset),
    edited: true,
    added: true,
    classification: a.classification,
  }))
  return [...held, ...unpriced, ...added]
}

export type Dimension = 'product' | 'country' | 'sector'

/** Something that makes up part of a slice - a fund in a country, a holding inside a fund. */
export type Part = { href?: string; label: string; value: number; icon?: string; note?: string }

export type Slice = {
  href?: string
  label: string
  value: number       // sandbox value
  share: number       // sandbox share of the visible total
  actualValue: number
  actualShare: number
  icon?: string       // overrides the card's icon for this slice
  parts?: Part[]      // what the slice is made of, biggest first, shown when it's clicked
}

/** Sums labelled amounts into slices, keeping track of what went into each. */
class Splitter {
  private totals = new Map<string, Slice & { partMap: Map<string, Part> }>()

  add(label: string, value: number, actualValue: number, part?: Part, icon?: string) {
    let t = this.totals.get(label)
    if (!t) {
      t = { label, value: 0, actualValue: 0, share: 0, actualShare: 0, icon, partMap: new Map() }
      this.totals.set(label, t)
    }
    t.value += value
    t.actualValue += actualValue
    if (part) {
      const p = t.partMap.get(part.label)
      if (p) p.value += part.value
      else t.partMap.set(part.label, { ...part })
    }
  }

  slices(total: number, actualTotal: number): Slice[] {
    return [...this.totals.values()]
      .map(({ partMap, ...t }) => ({
        ...t,
        share: total ? t.value / total : 0,
        actualShare: actualTotal ? t.actualValue / actualTotal : 0,
        parts: partMap.size ? [...partMap.values()].filter(p => p.value > 0.005).sort((a, b) => b.value - a.value) : undefined,
      }))
      .filter(s => s.value > 0.005 || s.actualValue > 0.005)
      .sort((a, b) => b.value - a.value || b.actualValue - a.actualValue)
  }
}

const KIND_ICON: Record<string, string> = { stock: '🏢', fund: '🧺', cash: '💷', unknown: '❔' }
const rowLabel = (r: Row) => (r.asset === 'GBP' ? 'Cash' : r.asset)
const rowIcon = (r: Row) => KIND_ICON[r.classification?.kind ?? (r.asset === 'GBP' ? 'cash' : 'unknown')]

function totals(rows: Row[]) {
  return [rows.reduce((s, r) => s + r.value, 0), rows.reduce((s, r) => s + r.actualValue, 0)] as const
}

/**
 * Splits visible rows by product, country or sector, for both actual and sandbox values. A fund's
 * value is spread over countries and sectors by its weights (which add up to 1), so every slice is
 * weighted by how much of each fund is held.
 */
export function breakdown(rows: Row[], dimension: Dimension): Slice[] {
  const visible = rows.filter(r => !r.hidden)
  const split = new Splitter()
  for (const row of visible) {
    if (dimension === 'product') {
      const inside = row.classification?.kind === 'fund' ? row.classification.holdings ?? [] : []
      split.add(rowLabel(row), row.value, row.actualValue)
      for (const h of inside) {
        split.add(rowLabel(row), 0, 0, { label: h.name, value: row.value * h.weight, note: h.country ?? h.sector ?? undefined })
      }
      continue
    }
    const weights = dimension === 'country' ? row.classification?.countries : row.classification?.sectors
    for (const [label, w] of Object.entries(weights ?? { Unknown: 1 })) {
      split.add(label, row.value * w, row.actualValue * w, { label: rowLabel(row), value: row.value * w, icon: rowIcon(row), note: pctOf(w) })
    }
  }
  return split.slices(...totals(visible))
}

const pctOf = (w: number) => (w > 0.9995 ? undefined : `${(w * 100).toFixed(w < 0.1 ? 1 : 0)}% of it`)

// Words that differ between how Yahoo and the fund issuers name the same company.
const NAME_NOISE = new Set(['INC', 'CORP', 'CORPORATION', 'CO', 'COMPANY', 'LTD', 'LIMITED', 'PLC', 'AG', 'SA', 'NV', 'SE', 'AB',
  'ASA', 'SPA', 'HOLDING', 'HOLDINGS', 'GROUP', 'CLASS', 'A', 'REG', 'THE', 'ORDINARY', 'SHARES', 'ADR', 'COM'])

/** A key that matches a company however it's written: 'Tesla, Inc.' and 'TESLA INC' both give 'TESLA'. */
export function companyKey(name: string) {
  const words = name.toUpperCase().replace(/[^A-Z0-9 ]+/g, ' ').split(/\s+/).filter(Boolean)
  return words.filter(w => !NAME_NOISE.has(w)).join(' ') || words.join(' ')
}

/**
 * Funds split into what they hold, merged with direct holdings, so e.g. a company held directly and
 * through two funds is one slice. The part of a fund outside its listed holdings is "Rest of <fund>".
 */
export function components(rows: Row[]): Slice[] {
  const visible = rows.filter(r => !r.hidden)
  const labels = new Map<string, string>()  // company key -> label, the first name seen wins
  const split = new Splitter()
  const add = (name: string, value: number, actualValue: number, via: Row, icon: string, note?: string) => {
    const key = name === 'Cash' ? 'Cash' : companyKey(name)
    if (!labels.has(key)) labels.set(key, name)
    const direct = via.classification?.kind !== 'fund'
    split.add(labels.get(key)!, value, actualValue, { label: direct ? `${rowLabel(via)} (direct)` : rowLabel(via), value, icon: rowIcon(via), note }, icon)
  }
  // Direct holdings first, so their names win over the issuers' shouty ones.
  const ordered = [...visible].sort((a, b) => Number(a.classification?.kind === 'fund') - Number(b.classification?.kind === 'fund'))
  for (const row of ordered) {
    const c = row.classification
    if (row.asset === 'GBP' || c?.kind === 'cash') {
      add('Cash', row.value, row.actualValue, row, '💷')
    } else if (c?.kind === 'fund' && c.holdings?.length) {
      for (const h of c.holdings) {
        add(h.name, row.value * h.weight, row.actualValue * h.weight, row, h.sector === 'Cash' ? '💷' : '🏢', pctOf(h.weight))
      }
      const rest = 1 - c.holdings.reduce((s, h) => s + h.weight, 0)
      if (rest > 0.0005) split.add(`Rest of ${row.asset}`, row.value * rest, row.actualValue * rest, undefined, '🧺')
    } else {
      add(c && c.kind === 'stock' ? row.name : row.asset, row.value, row.actualValue, row, rowIcon(row))
    }
  }
  return split.slices(...totals(visible))
}

/** The top `n` slices, with the rest folded into "Other" (whose parts are the folded slices). */
export function topSlices(slices: Slice[], n: number): Slice[] {
  if (slices.length <= n + 1) return slices
  const rest = slices.slice(n)
  const other = slices.find(s => s.label === 'Other')
  const folded = rest.filter(s => s !== other).concat(other ? [other] : [])
  const sum = (k: 'value' | 'share' | 'actualValue' | 'actualShare') => folded.reduce((s, x) => s + x[k], 0)
  return [
    ...slices.slice(0, n).filter(s => s !== other),
    {
      label: 'Other', value: sum('value'), share: sum('share'), actualValue: sum('actualValue'), actualShare: sum('actualShare'),
      parts: folded.filter(s => s.value > 0.005).map(s => ({ label: s.label, value: s.value, icon: s.icon })),
    },
  ]
}

export function isEmpty(s: Scenario) {
  return !s.hidden.length && !Object.keys(s.quantities).length && !s.added.length
}
