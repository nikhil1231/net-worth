export type AdvisorSettings = {
  cadence: 'weekly' | 'daily' | 'manual'; weekday: number; local_time: string
  goals: string; horizon: string; upcoming_expenses: string
  cash_buffer_gbp: number | null; cash_accounts: string[]
  concentration_pct: number; spending_change_gbp: number
  use_ai: boolean; model: string; max_output_tokens: number
}
export type AdvisorSettingsView = {
  values: AdvisorSettings; configured: boolean; timezone: string; next_run: string | null; accounts: string[]
}
export type AdvisorEvidence = {
  ref: string; explanation: string
  snapshot: { title: string; as_of: string; href: string; facts: Record<string, unknown> }
}
export type AdvisorFeedback = { feedback: 'new' | 'useful' | 'dismissed' | 'incorrect' | 'known'; answer: string }
export type AdvisorFinding = AdvisorFeedback & {
  topic: string; kind: string; priority: 'attention' | 'review' | 'information'
  title: string; observation: string; suggestion: string; caveats: string; evidence: AdvisorEvidence[]
}
export type AdvisorReport = {
  summary: string; findings: AdvisorFinding[]; period: { start: string; end: string; timezone: string }
  mode: 'calculated' | 'assisted'; warning: string; limitations: string[]
  evidence: Record<string, AdvisorEvidence['snapshot']>
}
export type AdvisorRun = {
  id: number; trigger: string; status: string; created_at: string; started_at: string | null
  finished_at: string | null; error: string | null; model: string
  usage: { total_tokens?: number; cost?: number }; report?: AdvisorReport | null
}
export type AdvisorOverview = {
  settings: AdvisorSettingsView; runs: AdvisorRun[]; latest: AdvisorRun | null
  feedback: Record<string, AdvisorFeedback>
}
async function request<T>(path = '', method = 'GET', value?: unknown): Promise<T> {
  const res = await fetch(`/api/advisor${path}`, {
    method, ...(value === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The request could not be completed. Check your settings and try again.')
  return data
}
export const advisorApi = {
  overview: () => request<AdvisorOverview>(),
  run: () => request<{ id: number; status: string }>('/run', 'POST'),
  history: (id: number) => request<AdvisorRun>(`/runs/${id}`),
  save: (settings: AdvisorSettings) => request<AdvisorSettingsView>('/settings', 'PUT', settings),
  feedback: (topic: string, value: AdvisorFeedback) => request<AdvisorFeedback>(`/findings/${encodeURIComponent(topic)}/feedback`, 'PUT', value),
}
