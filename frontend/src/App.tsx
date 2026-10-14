import { CurrencyProvider, CurrencyToggle, PrivacyToggle } from './Currency'
import { BrowserRouter, NavLink, Route, Routes } from 'react-router'
import { api } from './api'
import { useAsync } from './hooks'
import { AccountPage } from './pages/AccountPage'
import { Overview } from './pages/Overview'
import { Settings } from './pages/Settings'
import { Spending } from './pages/Spending'

/** Nav label for an account: "HL Stocks & Shares ISA" -> "ISA". */
function shortName(name: string) {
  if (/\bISA\b/.test(name)) return 'ISA'
  if (/\bSIPP\b/.test(name)) return 'SIPP'
  return name
}

export function App() {
  const { data: summary, error, setData } = useAsync(api.summary, [])
  const investments = summary?.accounts.filter(a => a.category === 'investments') ?? []

  return (
    <CurrencyProvider><BrowserRouter>
      <div className="backdrop" aria-hidden />
      <header className="topbar">
        <NavLink to="/" className="logo">
          <span className="logo-mark">💸</span>
          <span>net worth</span>
        </NavLink>
        <nav>
          <NavLink to="/" end>🏠 Overview</NavLink>
          {investments.map(a => (
            <NavLink key={a.name} to={`/accounts/${encodeURIComponent(a.name)}`}>📈 {shortName(a.name)}</NavLink>
          ))}
          <NavLink to="/spending">🧾 Spending</NavLink>
          <NavLink to="/settings">⚙️ Settings</NavLink>
          <CurrencyToggle />
          <PrivacyToggle />
        </nav>
      </header>
      <main>
        {error && <div className="page"><div className="banner bad">😬 Couldn't reach the server: {error}</div></div>}
        {!summary && !error && <div className="page"><div className="loading-card">💸 Counting your money…</div></div>}
        {summary && (
          <Routes>
            <Route path="/" element={<Overview summary={summary} onRefreshed={setData} />} />
            <Route path="/accounts/:name" element={<AccountPage onRefreshed={setData} />} />
            <Route path="/accounts/:name/chains/:chain" element={<AccountPage onRefreshed={setData} />} />
            <Route path="/accounts/:name/wallets/:wallet" element={<AccountPage onRefreshed={setData} />} />
            <Route path="/spending" element={<Spending />} />
            <Route path="/settings" element={<Settings summary={summary} onSummary={setData} />} />
            <Route path="*" element={<div className="page"><div className="banner bad">🤷 Nothing here. <NavLink to="/">Back to overview</NavLink></div></div>} />
          </Routes>
        )}
      </main>
    </BrowserRouter></CurrencyProvider>
  )
}
