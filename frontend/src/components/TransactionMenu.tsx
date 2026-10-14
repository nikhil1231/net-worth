import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { RecurringType } from '../api'

const recurringOptions: [RecurringType, string][] = [
  ['auto', 'Automatic detection'],
  ['monthly', 'Monthly spend'],
  ['subscription', 'Monthly subscription'],
  ['none', 'Not recurring'],
]

/** Native popovers dismiss on outside click/Escape and escape the table's scroll container. */
export function TransactionMenu({ label, value, disabled, onChange }: {
  label: string; value: RecurringType; disabled: boolean; onChange: (value: RecurringType) => void
}) {
  const id = useId()
  const popup = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  return <>
    <button type="button" className={`transaction-menu-trigger ${value === 'monthly' || value === 'subscription' ? 'active' : ''}`} aria-label={`Recurring settings for ${label}`} title="Recurring payment settings"
      aria-haspopup="dialog" popoverTarget={id} disabled={disabled}
      onClick={event => {
        const rect = event.currentTarget.getBoundingClientRect()
        setPosition({ top: Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 260)),
          left: Math.max(8, Math.min(rect.right - 256, window.innerWidth - 264)) })
      }}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="m17 2 4 4-4 4" /><path d="M3 11V9a3 3 0 0 1 3-3h15" />
        <path d="m7 22-4-4 4-4" /><path d="M21 13v2a3 3 0 0 1-3 3H3" />
      </svg></button>
    {createPortal(<div id={id} ref={popup} popover="auto" role="dialog" aria-label={`Recurring settings for ${label}`}
      className="transaction-menu" style={position}>
      <strong>Recurring payment</strong>
      <p>Applies to this merchant’s past and future expenses in this bank account.</p>
      {recurringOptions.map(([option, text]) => <button type="button" key={option}
        className={value === option ? 'selected' : ''} aria-pressed={value === option}
        onClick={() => { popup.current?.hidePopover(); onChange(option) }}>
        <span>{text}</span><span aria-hidden>{value === option ? '✓' : ''}</span>
      </button>)}
    </div>, document.body)}
  </>
}
