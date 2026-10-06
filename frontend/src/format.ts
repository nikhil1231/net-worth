export function pct(v: number, digits = 1) {
  return `${(v * 100).toFixed(digits)}%`
}

export function signedPct(v: number, digits = 1) {
  return `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(digits)}%`
}

/** Percentage-point change, for shifts in allocation share. */
export function signedPp(v: number) {
  return `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(1)}pp`
}

export function units(v: number) {
  if (v === 0) return '0'
  const digits = Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 1 ? 2 : 6
  return v.toLocaleString('en-GB', { maximumFractionDigits: digits })
}

export function ago(iso: string | null) {
  if (!iso) return 'never'
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export function greeting() {
  const h = new Date().getHours()
  if (h < 5) return 'Burning the midnight oil'
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}
