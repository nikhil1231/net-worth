import { type ReactNode, createContext, useContext, useEffect, useMemo } from 'react'
import { api } from './api'
import { useAsync, useStoredState } from './hooks'
import { units } from './format'
import { MASK, moneyFormatter, type Currency } from './money'

const defaults = moneyFormatter('GBP', { GBP: 1 })
const CurrencyContext = createContext({
  ...defaults, select: (_currency: Currency) => {}, usdAvailable: false,
  rateTitle: 'Loading exchange rate…',
  units, setHidden: (_hidden: boolean) => {},
})

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const [selected, select] = useStoredState<Currency>('networth:display-currency', 'GBP')
  const [hidden, setHidden] = useStoredState('networth:hide-values', false)
  const { data, error, reload } = useAsync(api.fx, [])
  useEffect(() => {
    const timer = window.setInterval(reload, 15 * 60 * 1000)
    return () => window.clearInterval(timer)
  }, [reload])
  const value = useMemo(() => {
    const usdAvailable = !!data?.rates.USD
    const currency = selected === 'USD' && usdAvailable ? 'USD' : 'GBP'
    return {
      ...moneyFormatter(currency, data?.rates ?? { GBP: 1 }, hidden), select, usdAvailable,
      units: (value: number) => hidden ? MASK : units(value), setHidden,
      rateTitle: data ? `1 GBP = ${data.rates.USD.toFixed(4)} USD · updated ${new Date(data.updated_at).toLocaleString('en-GB')}`
        : error ? 'Exchange rate unavailable' : 'Loading exchange rate…',
    }
  }, [selected, select, data, error, hidden, setHidden])
  return <CurrencyContext.Provider value={value}>{children}</CurrencyContext.Provider>
}

export const useMoney = () => useContext(CurrencyContext)

export function CurrencyToggle() {
  const { currency, select, usdAvailable, rateTitle } = useMoney()
  return <div className="pills currency-toggle" role="group" aria-label="Display currency">
    <button type="button" className={currency === 'GBP' ? 'on' : ''} aria-pressed={currency === 'GBP'}
      onClick={() => select('GBP')}>£ GBP</button>
    <button type="button" className={currency === 'USD' ? 'on' : ''} aria-pressed={currency === 'USD'}
      disabled={!usdAvailable} title={rateTitle} onClick={() => select('USD')}>$ USD</button>
  </div>
}

export function PrivacyToggle() {
  const { hidden, setHidden } = useMoney()
  const label = hidden ? 'Show values' : 'Hide values'
  return <button type="button" className="privacy-toggle" aria-pressed={hidden} aria-label={label} title={label}
    onClick={() => setHidden(!hidden)}>
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {hidden ? <>
        <path d="M10.7 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-2.2 3.2M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6" />
        <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M2 2l20 20" />
      </> : <>
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
        <circle cx="12" cy="12" r="3" />
      </>}
    </svg>
  </button>
}
