import { useState } from 'react'
import { spendingApi, type SpendingTransaction } from '../api'
import { CloseButton, Modal } from './Modal'

/** Your own note for a transaction, shown instead of the bank's description. */
export function TransactionLabel({ transaction, onSaved, onClose }: { transaction: SpendingTransaction; onSaved: () => void; onClose: () => void }) {
  const [label, setLabel] = useState(transaction.label ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const save = async (value: string) => {
    setBusy(true); setError('')
    try { await spendingApi.edit(transaction.id, { label: value }); onSaved(); onClose() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  return <Modal open onClose={onClose} className="transaction-label-modal" ariaLabel="Transaction label">
    <form className="modal-body" onSubmit={e => { e.preventDefault(); void save(label) }}>
      <div className="modal-head"><div><p className="modal-kicker muted">Transaction</p><h2>{transaction.label ? 'Edit label' : 'Add a label'}</h2></div><CloseButton onClose={onClose} /></div>
      <fieldset className="form" disabled={busy}>
        <label className="field"><span>Label</span>
          <input data-autofocus maxLength={100} value={label} placeholder={transaction.description} onChange={e => setLabel(e.target.value)} />
          <small>Shown under {transaction.merchant} instead of the bank’s description: {transaction.description}</small>
        </label>
      </fieldset>
      {error && <div className="banner bad" role="alert">{error}</div>}
      <div className="form-actions">
        {transaction.label && <button type="button" className="btn ghost danger-text" disabled={busy} onClick={() => void save('')}>Clear label</button>}
        <span className="spacer" />
        <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
      </div>
    </form>
  </Modal>
}
