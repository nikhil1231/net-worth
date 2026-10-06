import { useMoney } from '../Currency'
import { type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { colorFor } from '../colors'
import { pct, signedPp } from '../format'
import { type Part, type Slice, topSlices } from '../scenario'
import { Donut } from './Donut'

type Props = {
  title: string
  emoji: string
  slices: Slice[]
  icon?: (label: string) => string | undefined
  showDelta: boolean
  note?: string
  max?: number
  colorOf?: (label: string) => string | undefined
  labelOf?: (label: string) => string
  partsLabel?: string     // what a slice's parts are, e.g. "Held through"
  actions?: ReactNode     // extra controls in the header
  onExpand?: () => void   // shows an expand button in the header
  size?: number           // donut size
  className?: string
}

export function BreakdownCard({
  title, emoji, slices, icon, showDelta, note, max = 8, colorOf, labelOf = l => l, partsLabel, actions, onExpand, size = 200, className = '',
}: Props) {
  const { money } = useMoney()
  const [active, setActive] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const shown = topSlices(slices, max)
  const iconOf = (s: Slice) => s.icon ?? icon?.(s.label)
  const toggle = (label: string) => setOpen(o => (o === label ? null : label))
  const openRef = useRef<HTMLLIElement>(null)

  // The parts popover closes on a click anywhere else, or Escape (without also closing a modal around it).
  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => !openRef.current?.contains(e.target as Node) && setOpen(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      e.stopPropagation()
      setOpen(null)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [open])

  const colors = useMemo(() => sliceColors(slices, colorOf), [slices, colorOf])

  const total = shown.reduce((s, x) => s + x.value, 0)

  return (
    <section className={`card breakdown ${className}`} onMouseLeave={() => { setActive(null); setOpen(null) }}>
      <header className="card-head">
        <h3><span className="emoji">{emoji}</span> {title}</h3>
        <div className="card-head-side">
          {note && <span className="muted small">{note}</span>}
          {actions}
          {onExpand && (
            <button className="icon-btn plain" onClick={onExpand} title="Expand" aria-label={`Expand ${title}`}>⤢</button>
          )}
        </div>
      </header>
      {total <= 0 ? (
        <p className="empty">Nothing to split - everything's hidden 🙈</p>
      ) : (
        <div className="breakdown-body">
          <Donut
            slices={shown.filter(s => s.value > 0).map(s => ({ label: s.label, display: labelOf(s.label), value: s.value, color: colors.get(s.label)!, icon: iconOf(s) }))}
            active={active ?? open}
            onActive={setActive}
            onSelect={label => shown.some(s => s.label === label && (s.parts?.length || s.href)) && toggle(label)}
            centerTitle="Total"
            centerValue={total}
            size={size}
          />
          <ol className="legend">
            {shown.map(s => {
              const delta = s.share - s.actualShare
              const expandable = !!(s.parts?.length || s.href)
              const isOpen = open === s.label && expandable
              return (
                <li
                  key={s.label}
                  ref={isOpen ? openRef : undefined}
                  className={`${active === s.label || isOpen ? 'active' : active ? 'dim' : ''} ${expandable ? 'expandable' : ''}`}
                  onMouseEnter={() => setActive(s.label)}
                  onMouseLeave={() => { setActive(null); setOpen(null) }}
                >
                  <div
                    className="legend-row"
                    role={expandable ? 'button' : undefined}
                    tabIndex={expandable ? 0 : undefined}
                    aria-expanded={expandable ? isOpen : undefined}
                    onClick={() => expandable && toggle(s.label)}
                    onKeyDown={e => expandable && (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), toggle(s.label))}
                  >
                    <span className="legend-name">
                      <span className="swatch" style={{ background: colors.get(s.label) }} />
                      {iconOf(s) && <span className="legend-icon">{iconOf(s)}</span>}
                      <span className="truncate" title={s.label}>{labelOf(s.label)}</span>
                      {expandable && <span className={`chevron ${isOpen ? 'open' : ''}`} aria-hidden>›</span>}
                    </span>
                    <span className="legend-bar">
                      <span style={{ width: `${Math.max(2, s.share * 100)}%`, background: colors.get(s.label) }} />
                    </span>
                    <span className="legend-pct">{pct(s.share)}</span>
                    <span className="legend-money muted">{money(s.value)}</span>
                    {showDelta && (
                      <span className={`delta ${Math.abs(delta) < 0.0005 ? 'flat' : delta > 0 ? 'up' : 'down'}`}>
                        {Math.abs(delta) < 0.0005 ? '·' : signedPp(delta)}
                      </span>
                    )}
                  </div>
                  {isOpen && <Parts parts={s.parts ?? []} href={s.href} total={s.value} label={partsLabel} color={colors.get(s.label)!} />}
                </li>
              )
            })}
          </ol>
        </div>
      )}
    </section>
  )
}

/** What a slice is made of, floating over the rows below it (or above, near the bottom of the screen). */
function Parts({ parts, total, label, color, href }: { parts: Part[]; total: number; label?: string; color: string; href?: string }) {
  const { money } = useMoney()
  const ref = useRef<HTMLDivElement>(null)
  const [above, setAbove] = useState(false)

  useLayoutEffect(() => {
    const box = ref.current?.getBoundingClientRect()
    const row = ref.current?.parentElement?.getBoundingClientRect()
    if (box && row && box.bottom > window.innerHeight - 8 && row.top - box.height > 8) setAbove(true)
  }, [])

  return (
    <div ref={ref} className={`parts popover ${above ? 'above' : ''}`} style={{ ['--c' as string]: color }} role="dialog" aria-label={label}>
      {label && <div className="parts-title">{label}</div>}
      {href && <Link className="popover-link" to={href}>Open details ↗</Link>}
      <ul>
        {parts.map((p, i) => (
          <li key={p.label + i}>
            <span className="parts-name">
              {p.icon && <span>{p.icon}</span>}
              {p.href ? <Link className="truncate" to={p.href}>{p.label} ↗</Link> : <span className="truncate" title={p.label}>{p.label}</span>}
              {p.note && <span className="parts-note truncate">{p.note}</span>}
            </span>
            <span className="parts-pct">{pct(total ? p.value / total : 0)}</span>
            <span className="parts-money">{money(p.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Colours follow the actual ranking, so they don't jump about while editing in the sandbox. */
export function sliceColors(slices: Slice[], colorOf?: (label: string) => string | undefined) {
  const order = [...slices].sort((a, b) => b.actualValue - a.actualValue).map(s => s.label)
  const map = new Map<string, string>()
  let i = 0
  for (const label of [...order, 'Other']) {
    if (!map.has(label)) map.set(label, colorOf?.(label) ?? colorFor(label, ['Other', 'Cash', 'Unknown'].includes(label) ? 0 : i++))
  }
  return map
}
