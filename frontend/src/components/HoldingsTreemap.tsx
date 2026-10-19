import { useMoney } from '../Currency'
import { Link } from 'react-router'
import { ChartFrame, ChartTooltip as Tooltip } from './ChartTooltip'
import { ResponsiveContainer, Treemap } from 'recharts'
import type { Summary } from '../api'
import { isCashAsset, PALETTE } from '../colors'
import { pct } from '../format'

type Tile = { name: string; label: string; size: number; fill: string; accounts: string[] }

/** Every holding across every account, same assets merged, as one colourful wall of tiles. */
export function HoldingsTreemap({ summary, colors }: { summary: Summary; colors: Map<string, string> }) {
  const { money } = useMoney()
  const merged = new Map<string, Tile>()
  for (const account of summary.accounts) {
    for (const h of account.holdings) {
      const cash = isCashAsset(h.asset)
      const key = cash ? 'Cash' : h.asset
      const tile = merged.get(key) ?? { name: key, label: cash ? 'Cash' : (h.name ?? h.asset), size: 0, fill: '', accounts: [] }
      tile.size += h.value
      if (!tile.accounts.includes(account.name)) tile.accounts.push(account.name)
      merged.set(key, tile)
    }
  }
  const tiles = [...merged.values()].filter(t => t.size > 0).sort((a, b) => b.size - a.size)
  tiles.forEach((t, i) => (t.fill = colors.get(t.name) ?? PALETTE[i % PALETTE.length]))
  const total = tiles.reduce((s, t) => s + t.size, 0)

  return (
    <section className="card">
      <header className="card-head">
        <h3><span className="emoji">🧱</span> Everything you own</h3>
        <span className="muted small">{tiles.length} holdings, sized by value</span>
      </header>
      <ChartFrame hover><ResponsiveContainer width="100%" height={340}>
        <Treemap
          data={tiles}
          dataKey="size"
          nameKey="name"
          aspectRatio={1.6}
          isAnimationActive={false}
          content={<TileShape total={total} />}
        >
          <Tooltip
            content={({ active, payload }) => {
              const t = active && (payload?.[0]?.payload as Tile | undefined)
              return t ? (
                <div className="tooltip">
                  <div className="tooltip-title">{t.name} · {t.label}</div>
                  <div className="tooltip-total">{money(t.size)}</div>
                  <div className="muted small">{pct(t.size / total)} of everything</div>
                  <div className="muted small">in {t.accounts.map(account =>
                    <Link key={account} to={`/accounts/${encodeURIComponent(account)}`}>{account} ↗ </Link>)}</div>
                </div>
              ) : null
            }}
          />
        </Treemap>
      </ResponsiveContainer></ChartFrame>
    </section>
  )
}

type ShapeProps = { depth?: number; x?: number; y?: number; width?: number; height?: number; name?: string; size?: number; fill?: string; total: number }

function TileShape({ depth, x = 0, y = 0, width = 0, height = 0, name, size = 0, fill, total }: ShapeProps) {
  if (depth !== 1 || width < 2 || height < 2) return null  // depth 0 is the invisible root
  const big = width > 70 && height > 44
  return (
    <g>
      <rect x={x + 2} y={y + 2} width={width - 4} height={height - 4} rx={12} fill={fill} />
      {big && (
        <>
          <text x={x + 12} y={y + 26} fill="#fff" fontWeight={800} fontSize={Math.min(20, width / 6)} style={{ fontFamily: 'var(--display)' }}>
            {name}
          </text>
          {height > 64 && (
            <text x={x + 12} y={y + 46} fill="#fff" fillOpacity={0.9} fontSize={13} fontWeight={600}>
              {pct(size / total)}
            </text>
          )}
        </>
      )}
    </g>
  )
}
