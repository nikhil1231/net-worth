import { type ReactNode, useEffect, useRef, useState } from 'react'

/** Click/keyboard activation with dismissal when leaving the trigger and its popup. */
export function Popover({ trigger, children, label, warning = false, hover = false }: {
  trigger: ReactNode; children: ReactNode; label: string; warning?: boolean; hover?: boolean
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  return <span className="inline-popover" ref={ref}
    onMouseLeave={() => setOpen(false)}
    onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false) }}
    onKeyDown={event => { if (event.key === 'Escape') setOpen(false) }}>
    <button type="button" className={warning ? 'token-warning' : 'ticker link'}
      aria-label={label} aria-expanded={open}
      onMouseEnter={() => hover && setOpen(true)} onClick={() => setOpen(true)}>
      {trigger}
    </button>
    {open && <span className="inline-popover-content" role={warning ? 'tooltip' : 'dialog'} aria-label={label}>
      {children}
    </span>}
  </span>
}
