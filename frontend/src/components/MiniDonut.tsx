import { useMoney } from '../Currency'
import { useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Cell, Pie, PieChart } from 'recharts'
import type { Account, AccountDetail } from '../api'
import { pct } from '../format'
import { useStoredState } from '../hooks'
import { breakdown, buildRows, EMPTY_SCENARIO, type Scenario, topSlices } from '../scenario'
import { sliceColors } from './BreakdownCard'

const SIZE = 56

/** The account page's "By product" split, tiny: no text until you hover a slice. */
export function MiniDonut({ account }: { account: Account }) {
  const { money } = useMoney()
  const [scenario] = useStoredState<Scenario>(`networth:scenario:${account.name}:`, EMPTY_SCENARIO)
  const slices = useMemo(() => {
    const detail = { ...account, classifications: {} } as unknown as AccountDetail
    return topSlices(breakdown(buildRows(detail, scenario), 'product'), 8).filter(s => s.value > 0)
  }, [account, scenario])
  const colors = useMemo(() => sliceColors(slices), [slices])
  const [hover, setHover] = useState<{ label: string; x: number; y: number } | null>(null)
  const total = slices.reduce((s, x) => s + x.value, 0)
  const active = slices.find(s => s.label === hover?.label)

  if (total <= 0) return null
  return (
    <div className="mini-donut" style={{ width: SIZE, height: SIZE }} onMouseLeave={() => setHover(null)}>
      <PieChart width={SIZE} height={SIZE}>
        <Pie
          data={slices} dataKey="value" nameKey="label"
          innerRadius={SIZE * 0.3} outerRadius={SIZE / 2}
          paddingAngle={slices.length > 1 ? 3 : 0} cornerRadius={3} stroke="none"
          startAngle={90} endAngle={-270} isAnimationActive={false}
        >
          {slices.map(s => (
            <Cell
              key={s.label}
              fill={colors.get(s.label)}
              fillOpacity={hover && hover.label !== s.label ? 0.3 : 1}
              style={{ transition: 'fill-opacity .2s', outline: 'none' }}
              onMouseMove={e => setHover({ label: s.label, x: e.clientX, y: e.clientY })}
            />
          ))}
        </Pie>
      </PieChart>
      {active && hover && createPortal(
        <div className="tooltip mini-donut-tip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          <div className="tooltip-row">
            <span className="swatch" style={{ background: colors.get(active.label) }} />
            <span>{active.label}</span>
            <b>{pct(active.value / total)}</b>
          </div>
          <div className="muted small">{money(active.value)}</div>
        </div>,
        document.body,
      )}
    </div>
  )
}
