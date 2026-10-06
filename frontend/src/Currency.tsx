import { type ReactNode, createContext, useContext, useEffect, useMemo } from 'react'
import { api } from './api'
import { useAsync, useStoredState } from './hooks'
import { moneyFormatter, type Currency } from './money'

const defaults = moneyFormatter('GBP', { GBP: 1 })
const CurrencyContext = createContext({
  ...defaults, select: (_currency: Currency) => {}, usdAvailable: false,
  rateTitle: 'Loading exchange rate…',
})

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const [selected, select] = useStoredState<Currency>('networth:display-currency', 'GBP')
  const { data, error, reload } = useAsync(api.fx, [])
  useEffect(() => {
    const timer = window.setInterval(reload, 15 * 60 * 1000)
    return () => window.clearInterval(timer)
  }, [reload])
  const value = useMemo(() => {
    const usdAvailable = !!data?.rates.USD
    const currency = selected === 'USD' && usdAvailable ? 'USD' : 'GBP'
    return {
      ...moneyFormatter(currency, data?.rates ?? { GBP: 1 }), select, usdAvailable,
      rateTitle: data ? `1 GBP = ${data.rates.USD.toFixed(4)} USD · updated ${new Date(data.updated_at).toLocaleString('en-GB')}`
        : error ? 'Exchange rate unavailable' : 'Loading exchange rate…',
    }
  }, [selected, select, data, error])
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
