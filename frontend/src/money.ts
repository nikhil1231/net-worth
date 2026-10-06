export type Currency = 'GBP' | 'USD'

/** Stored valuations stay in GBP; all display conversion happens at this boundary. */
export function moneyFormatter(currency: Currency, rates: Record<string, number>) {
  const factor = currency === 'USD' ? rates.USD : 1
  if (!(factor > 0) || !Number.isFinite(factor)) throw new Error('Missing exchange rate')
  const locale = currency === 'USD' ? 'en-US' : 'en-GB'
  const format = new Intl.NumberFormat(locale, { style: 'currency', currency, maximumFractionDigits: 0 })
  const exact = new Intl.NumberFormat(locale, { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const compact = new Intl.NumberFormat(locale, { style: 'currency', currency, notation: 'compact', minimumFractionDigits: 0, maximumFractionDigits: 1 })
  const native = (value: number, source: string, isCompact: boolean) => {
    const pence = source === 'GBp' || source === 'GBX'
    const code = pence ? 'GBP' : source.toUpperCase()
    const rate = code === 'GBP' ? 1 : rates[code]
    if (rate > 0) {
      const gbp = (pence ? value / 100 : value) / rate
      return (isCompact ? compact : exact).format(gbp * factor)
    }
    return new Intl.NumberFormat('en-GB', {
      style: 'currency', currency: code,
      ...(isCompact ? { notation: 'compact' as const } : { maximumFractionDigits: 2 }),
    }).format(value)
  }
  return {
    currency, factor, symbol: currency === 'USD' ? '$' : '£',
    toDisplay: (gbp: number) => gbp * factor,
    toGBP: (display: number) => display / factor,
    money: (gbp: number) => format.format(gbp * factor),
    moneyExact: (gbp: number) => exact.format(gbp * factor),
    moneyCompact: (gbp: number) => compact.format(gbp * factor),
    signedMoney: (gbp: number) => `${gbp >= 0 ? '+' : '−'}${format.format(Math.abs(gbp) * factor)}`,
    nativeMoney: (value: number, source: string) => native(value, source, false),
    nativeCompact: (value: number | undefined, source: string) => value === undefined ? undefined : native(value, source, true),
  }
}
