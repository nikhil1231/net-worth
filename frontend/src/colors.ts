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

/** Fiat and stablecoins count as cash wherever they're held, matching CASH_ASSETS in networth/reports.py. */
const CASH_ASSETS: Record<string, true> = {
  GBP: true, USD: true, EUR: true, USDC: true, 'USDC.E': true, USDT: true, USDB: true, DAI: true,
  USDS: true, USDE: true, PYUSD: true, FDUSD: true, TUSD: true, BUSD: true, GUSD: true, USDP: true,
  FRAX: true, LUSD: true, EURC: true,
}
export const isCashAsset = (asset: string) => CASH_ASSETS[asset.toUpperCase()] === true

const CATEGORY: Record<string, { color: string; emoji: string }> = {
  investments: { color: '#7c5cff', emoji: '📈' },
  crypto: { color: '#ffb020', emoji: '💰' },
  cash: { color: '#18c29c', emoji: '💷' },
  property: { color: '#ff4fa3', emoji: '🏡' },
  pension: { color: '#2f9bff', emoji: '🌴' },
  liabilities: { color: '#ff5d5d', emoji: '💳' },
}

export function categoryStyle(category: string, index = 0) {
  return CATEGORY[category] ?? { color: PALETTE[(index + 4) % PALETTE.length], emoji: '✨' }
}

const SPECIAL_COLORS: Record<string, string> = {
  Other: OTHER_COLOR, Cash: CASH_COLOR, Unknown: UNKNOWN_COLOR,
}

// Keep the cash green out of the asset palette so a holding never matches the Cash slice.
const ASSET_PALETTE = PALETTE.filter(color => color !== CASH_COLOR)

/** Stable colour per label, so e.g. "Taiwan" is the same colour on every chart. */
export function colorFor(label: string, index: number) {
  return SPECIAL_COLORS[label] ?? PALETTE[index % PALETTE.length]
}

/**
 * One colour per label, in the order given (normally by total value), so an asset keeps its
 * colour between the account donuts and the treemap. Labels stay distinct, including past the
 * end of the palette, so neighbouring slices never share a colour.
 */
export function assetColorMap(labels: Iterable<string>) {
  const map = new Map<string, string>()
  let index = 0
  for (const label of labels) {
    if (map.has(label)) continue
    const special = SPECIAL_COLORS[label]
    if (special) {
      map.set(label, special)
      continue
    }
    map.set(label, index < ASSET_PALETTE.length
      ? ASSET_PALETTE[index]
      : `hsl(${((index * 137.508) % 360).toFixed(2)} 72% 62%)`)
    index++
  }
  return map
}

export const KIND_EMOJI: Record<string, string> = { stock: '🏢', fund: '🧺', cash: '💷', unknown: '❔' }
