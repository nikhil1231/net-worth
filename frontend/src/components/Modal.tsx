import { type ReactNode, useEffect, useRef } from 'react'

type Props = { open: boolean; onClose: () => void; children: ReactNode; className?: string }

/** A native <dialog>: Escape, focus trapping and the backdrop come for free. Click outside to close. */
export function Modal({ open, onClose, children, className = '' }: Props) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      className={`modal ${className}`}
      onClose={onClose}
      onClick={e => e.target === ref.current && onClose()}
    >
      {open && children}
    </dialog>
  )
}

export function CloseButton({ onClose }: { onClose: () => void }) {
  return <button className="icon-btn plain" onClick={onClose} aria-label="Close" title="Close">✕</button>
}
