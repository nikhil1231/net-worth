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

export type RecurringType = 'auto' | 'monthly' | 'subscription' | 'none'
export type SpendingTransaction = {
  id: string; account: string; bank_account: string; date: string; merchant: string; description: string
  amount: number; category: string; kind: 'expense' | 'income' | 'refund' | 'transfer'
  pending: boolean; possible_transfer: boolean; recurring_type: RecurringType
  time: string | null; label: string | null; inferred: ('category' | 'kind')[]
}
export type RecurringPayment = {
  id: string; account: string; merchant: string; status: 'detected' | 'confirmed' | 'dismissed' | 'cancelled'
  frequency: string; recurring_type: RecurringType; manual: boolean; amount: number; monthly: number; last_date: string; next_date: string
  overdue: boolean; variable: boolean; price_change: number
  active: boolean; inactive: boolean; coverage_stale: boolean; description_contains: string
}
export type SpendingPeriod = 'month' | '3m' | '6m' | 'ytd' | '1y' | 'all'
export type SpendingReport = {
  period: SpendingPeriod; start: string; syncing: boolean
  month: string
  summary: { spent: number; refunds: number; net_spent: number; income: number; pending: number; committed: number }
  categories: { category: string; amount: number }[]
  history: { month: string; spent: number; refunds: number; income: number }[]
  pace: { day: number; current: number | null; previous: number }[]
  transactions: SpendingTransaction[]; recurring: RecurringPayment[]
  accounts: { name: string; type: string; institution: string; connection_status: string; connection_detail: string; sync_enabled: boolean; first_date: string | null; last_date: string | null; count: number; last_success?: string; last_error?: string; history_from?: string }[]
  category_options: string[]; review_count: number
}
export type StatementPreview = {
  count: number; new_count: number; duplicates: number; first_date: string; last_date: string
  preview: SpendingTransaction[]; committed: boolean
}
const jsonBody = (method: string, value: unknown) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) })
export type LunchFlowAccount = { id: string; name: string; institution: string; currency: string; status: string }
export type LunchFlowMapping = { id: string; account: string; start_date: string | null }
export type LunchFlowState = {
  configured: boolean
  bindings: (LunchFlowMapping & { institution: string; enabled: number })[]
  choices: { name: string; start_date: string }[]
}
export const spendingApi = {
  lunchflow: () => request<LunchFlowState>('/api/spending/lunchflow'),
  lunchflowAccounts: () => request<LunchFlowAccount[]>('/api/spending/lunchflow/accounts', { method: 'POST' }),
  saveLunchflow: (mappings: LunchFlowMapping[]) => request<LunchFlowState>('/api/spending/lunchflow', jsonBody('PUT', { mappings })),
  report: (month: string, account: string, period: SpendingPeriod = 'month') => request<SpendingReport>(`/api/spending?month=${month}&period=${period}${account ? `&account=${encodeURIComponent(account)}` : ''}`),
  sync: () => request<{ account: string; count: number; error: string | null }[]>('/api/spending/sync', { method: 'POST' }),
  edit: (id: string, values: { category?: string; kind?: string; apply_rule?: boolean; recurring_type?: RecurringType; label?: string }) => request(`/api/spending/transactions/${encodeURIComponent(id)}`, jsonBody('PATCH', values)),
  recurring: (r: RecurringPayment, status: RecurringPayment['status']) => request(`/api/spending/recurring/${r.id}`, jsonBody('PATCH', { account: r.account, merchant: r.merchant, status })),
  import: (account: string, text: string, mapping: Record<string, string | boolean>, commit = false) => request<StatementPreview>('/api/spending/import', jsonBody('POST', { account, text, mapping, commit })),
}
