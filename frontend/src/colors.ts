// A bright, candy-ish palette. Ordered so neighbours in a donut never look alike.
export const PALETTE = [
  '#7c5cff', // violet
  '#ff4fa3', // pink
  '#ffb020', // mango
  '#18c29c', // mint
  '#2f9bff', // sky
  '#ff6b4a', // coral
  '#a3d930', // lime
  '#b45cff', // grape
  '#14bcd4', // lagoon
  '#ff8fc8', // bubblegum
  '#5b6cff', // indigo
  '#f5d200', // lemon
]

export const OTHER_COLOR = '#b8b2cc'
export const CASH_COLOR = '#18c29c'
export const UNKNOWN_COLOR = '#d6d1e6'

const CATEGORY: Record<string, { color: string; emoji: string }> = {
  investments: { color: '#7c5cff', emoji: '📈' },
  crypto: { color: '#ffb020', emoji: '💰' },
  cash: { color: '#18c29c', emoji: '💷' },
  property: { color: '#ff4fa3', emoji: '🏡' },
  pension: { color: '#2f9bff', emoji: '🌴' },
}

export function categoryStyle(category: string, index = 0) {
  return CATEGORY[category] ?? { color: PALETTE[(index + 4) % PALETTE.length], emoji: '✨' }
}

/** Stable colour per label, so e.g. "Taiwan" is the same colour on every chart. */
export function colorFor(label: string, index: number) {
  if (label === 'Other') return OTHER_COLOR
  if (label === 'Cash') return CASH_COLOR
  if (label === 'Unknown') return UNKNOWN_COLOR
  return PALETTE[index % PALETTE.length]
}

export const KIND_EMOJI: Record<string, string> = { stock: '🏢', fund: '🧺', cash: '💷', unknown: '❔' }
