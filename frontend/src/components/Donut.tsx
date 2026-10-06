import { useMoney } from '../Currency'
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'
import { pct } from '../format'

export type DonutSlice = { label: string; display?: string; value: number; color: string; icon?: string }

type Props = {
  slices: DonutSlice[]
  active: string | null
  onActive: (label: string | null) => void
  onSelect?: (label: string) => void
  centerTitle: string
  centerValue: number
  size?: number
}

export function Donut({ slices, active, onActive, onSelect, centerTitle, centerValue, size = 220 }: Props) {
  const { money } = useMoney()
  const total = slices.reduce((s, x) => s + x.value, 0)
  const activeSlice = slices.find(s => s.label === active)

  return (
    <div className="donut" style={{ width: size, height: size }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={slices}
            dataKey="value"
            nameKey="label"
            innerRadius="64%"
            outerRadius="100%"
            paddingAngle={slices.length > 1 ? 2.5 : 0}
            cornerRadius={8}
            stroke="none"
            startAngle={90}
            endAngle={-270}
            animationDuration={700}
            onMouseEnter={(_, i) => onActive(slices[i]?.label ?? null)}
            onMouseLeave={() => onActive(null)}
            onClick={(_, i) => slices[i] && onSelect?.(slices[i].label)}
            isAnimationActive
          >
            {slices.map(s => (
              <Cell
                key={s.label}
                fill={s.color}
                fillOpacity={active && active !== s.label ? 0.25 : 1}
                style={{ transition: 'fill-opacity .2s', cursor: 'pointer', outline: 'none' }}
              />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="donut-center">
        {activeSlice ? (
          <>
            <div className="donut-label">{activeSlice.icon} {activeSlice.display ?? activeSlice.label}</div>
            <div className="donut-value">{pct(total ? activeSlice.value / total : 0)}</div>
            <div className="donut-sub">{money(activeSlice.value)}</div>
          </>
        ) : (
          <>
            <div className="donut-label">{centerTitle}</div>
            <div className="donut-value">{money(centerValue)}</div>
          </>
        )}
      </div>
    </div>
  )
}
