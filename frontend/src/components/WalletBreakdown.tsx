import type { AccountDetail } from '../api'
import type { Slice } from '../scenario'
import { units } from '../format'
import { BreakdownCard } from './BreakdownCard'

const short = (address: string) => `${address.slice(0, 7)}…${address.slice(-5)}`
function slices(values: Record<string, number>): Slice[] {
  const total = Object.values(values).reduce((sum, v) => sum + v, 0)
  return Object.entries(values).map(([label, value]) => ({ label, value, actualValue: value,
    share: total ? value / total : 0, actualShare: total ? value / total : 0 }))
    .sort((a, b) => b.value - a.value)
}

export function WalletBreakdown({ detail }: { detail: AccountDetail }) {
  const wallets = detail.wallets ?? []
  const parent = detail.parent_account ?? detail.name
  const root = `/accounts/${encodeURIComponent(parent)}`
  const chainPath = (chain: string) => `${root}/chains/${encodeURIComponent(chain)}`
  const walletPath = (wallet: string) => `${root}/wallets/${encodeURIComponent(wallet)}`
  const chainValues: Record<string, number> = {}
  for (const w of wallets) for (const h of w.holdings) {
    if (h.quantity) chainValues[h.chain] = (chainValues[h.chain] ?? 0) + (h.value ?? 0)
  }
  const walletSlices = slices(Object.fromEntries(wallets.map(w => [w.address, w.value]))).map(slice => {
    const wallet = wallets.find(w => w.address === slice.label)!
    return { ...slice, href: walletPath(wallet.address), parts: wallet.holdings.filter(h => h.quantity !== 0).map(h => ({
      href: chainPath(h.chain), label: `${h.asset} · ${h.chain}`,
      value: h.value ?? 0,
      note: `${units(h.quantity)} units${h.value === null ? ' · unpriced' : ''}`,
    })).sort((a, b) => b.value - a.value) }
  })
  const chainSlices = slices(chainValues).map(slice => ({
    ...slice, href: chainPath(slice.label),
    parts: wallets.flatMap(wallet => wallet.holdings.filter(h => h.chain === slice.label && h.quantity).map(h => ({
      label: `${h.asset} · ${short(wallet.address)}`, value: h.value ?? 0,
      note: `${units(h.quantity)} units`, href: walletPath(wallet.address),
    }))),
  }))
  return <>
    <div className="banner">
      <div><b>{wallets.length} constituent wallets</b><p className="muted small">
        Combined balances across these addresses{Object.keys(chainValues).length > 1 ? ` and ${Object.keys(chainValues).length} chains` : ''}.
        Wallet balances and the charts below show actual holdings, including any hidden in the sandbox.
      </p></div>
    </div>
    {detail.wallet_breakdown_available ? <div className="grid two">
      <BreakdownCard title="By wallet" emoji="👛" slices={walletSlices} labelOf={short} partsLabel="Wallet balances" showDelta={false} note="Click an address for balances" />
      <BreakdownCard title="By chain" emoji="🔗" slices={chainSlices} partsLabel="Chain balances" showDelta={false} note="Actual balances" />
    </div> : <p className="footnote">Per-wallet balances will appear after the next successful refresh. Older snapshots contain combined balances only.</p>}

  </>
}
