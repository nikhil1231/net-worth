export type HoldingLocation = { wallet: string; chain: string; quantity: number; value: number | null; name: string | null }
export type Holding = {
  locations?: HoldingLocation[]
  asset: string
  name: string | null
  quantity: number
  price: number | null
  value: number
}

export type Account = {
  name: string
  category: string
  type: string
  value: number
  fetched_at: string | null
  holdings: Holding[]
  unpriced: Holding[]
  last_success: string | null
  last_error: string | null
}

export type Summary = {
  ts: string | null
  total: number
  categories: Record<string, number>
  category_accounts: Record<string, Record<string, number>> // which accounts make up each category
  accounts: Account[]
  changes: Record<string, { ts: string; value: number; previous: number }>
}

export type History = {
  keys: string[]
  points: { ts: string; values: Record<string, number>; total: number }[]
}

/** One holding inside a fund. Weights are fractions of the whole fund; the long tail is left out. */
export type Constituent = {
  name: string
  weight: number
  sector: string | null
  country: string | null
}

export type Classification = {
  kind: 'stock' | 'fund' | 'cash' | 'unknown'
  name: string
  symbol: string | null
  countries: Record<string, number>
  sectors: Record<string, number>
  holdings?: Constituent[]
  source: 'yahoo' | 'ishares' | 'xtrackers' | null
  price_gbp: number | null
  error: string | null
}

export type WalletDetail = {
  address: string
  label: string
  value: number
  fetched_at: string | null
  holdings: { asset: string; chain: string; quantity: number; value: number | null; price: number | null }[]
}
export type AccountDetail = Account & {
  parent_account?: string
  classifications: Record<string, Classification>
  wallets?: WalletDetail[]
  wallet_breakdown_available?: boolean
  unattributed_value?: number
}

export type Quote = Classification & { asset: string }

/** What Yahoo Finance has on a listing. `info` is Yahoo's own info dict, minus some noise. */
export type Details = {
  symbol: string
  info: Record<string, unknown>
  history: { date: string; close: number }[]
  fund?: {
    description: string | null
    asset_classes: Record<string, number>
    sectors: Record<string, number>
    top_holdings: { symbol: string; name: string | null; weight: number | null }[]
    operations: Record<string, number | null>
  }
}

/** How the settings page shows one connector param (networth/connectors/base.py Field). */
export type FieldSpec = {
  key: string
  label: string
  kind: 'text' | 'secret' | 'number' | 'list' | 'bool' | 'yaml'
  required: boolean
  help: string | null
  placeholder: string | null
  default: unknown
}

/** An account as written in accounts.yaml. Literal secrets come back as SECRET_MASK. */
export type AccountConfig = {
  name: string
  type: string
  category: string
  interval: number | null
  params: Record<string, unknown>
}

export type ConfigData = {
  path: string
  writable: boolean
  settings: { tick_minutes: number; default_interval: number }
  accounts: AccountConfig[]
  connectors: Record<string, { label: string; fields: FieldSpec[] }>
}

/** Sent back unchanged, it means "keep the saved secret" (networth/settings.py). */
export const SECRET_MASK = '••••••••'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      // not JSON
    }
    throw new Error(detail)
  }
  return res.json()
}

export type ExchangeRates = { base: 'GBP'; rates: Record<string, number>; updated_at: string }

export const api = {
  fx: () => request<ExchangeRates>('/api/fx'),
  summary: () => request<Summary>('/api/summary'),
  history: (days: number | null, group: 'category' | 'account') =>
    request<History>(`/api/history?group=${group}${days ? `&days=${days}` : ''}`),
  wallet: (name: string, wallet: string) => request<AccountDetail>(`/api/accounts/${encodeURIComponent(name)}/wallets/${encodeURIComponent(wallet)}`),
  chain: (name: string, chain: string) => request<AccountDetail>(`/api/accounts/${encodeURIComponent(name)}/chains/${encodeURIComponent(chain)}`),
  account: (name: string) => request<AccountDetail>(`/api/accounts/${encodeURIComponent(name)}`),
  details: (symbol: string) => request<Details>(`/api/details?symbol=${encodeURIComponent(symbol)}`),
  quote: (ticker: string) => request<Quote>(`/api/quote?ticker=${encodeURIComponent(ticker)}`),
  config: () => request<ConfigData>('/api/config'),
  saveAccount: (original: string | null, account: AccountConfig) =>
    request<ConfigData>(original === null ? '/api/config/accounts' : `/api/config/accounts/${encodeURIComponent(original)}`, {
      method: original === null ? 'POST' : 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(account),
    }),
  deleteAccount: (name: string) => request<ConfigData>(`/api/config/accounts/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  saveSettings: (settings: ConfigData['settings']) =>
    request<ConfigData>('/api/config/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    }),
  refresh: (account?: string) =>
    request<Summary>(`/api/refresh${account ? `?account=${encodeURIComponent(account)}` : ''}`, { method: 'POST' }),
}
