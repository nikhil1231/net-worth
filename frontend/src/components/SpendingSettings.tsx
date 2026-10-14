import { useState } from 'react'
import { type SpendingReport } from '../api'
import { Modal, CloseButton } from './Modal'
import { LunchFlowSetup } from './LunchFlowSetup'
import { StatementImport } from './StatementImport'

export function SpendingSettings({ accounts, onSaved, onClose }: { accounts: SpendingReport['accounts']; onSaved: () => void; onClose: () => void }) {
  const [tab, setTab] = useState<'banks' | 'statements'>('banks')
  return <Modal open onClose={onClose} className="spending-settings" ariaLabel="Transaction settings">
    <div className="modal-body">
      <div className="modal-head"><div><p className="modal-kicker muted">Spending</p><h2>Transaction settings</h2></div><CloseButton onClose={onClose} /></div>
      <div className="pills" role="tablist" aria-label="Transaction settings" onKeyDown={e => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return
        e.preventDefault()
        const next = e.key === 'Home' ? 'banks' : e.key === 'End' ? 'statements' : tab === 'banks' ? 'statements' : 'banks'
        setTab(next)
        e.currentTarget.querySelectorAll<HTMLButtonElement>('[role=tab]')[next === 'banks' ? 0 : 1]?.focus()
      }}>
        <button role="tab" id="bank-settings-tab" aria-controls="bank-settings-panel" aria-selected={tab === 'banks'} tabIndex={tab === 'banks' ? 0 : -1} className={tab === 'banks' ? 'on' : ''} onClick={() => setTab('banks')}>Bank connections</button>
        <button role="tab" id="statement-settings-tab" aria-controls="statement-settings-panel" aria-selected={tab === 'statements'} tabIndex={tab === 'statements' ? 0 : -1} className={tab === 'statements' ? 'on' : ''} onClick={() => setTab('statements')}>Statements</button>
      </div>
      <div role="tabpanel" id="bank-settings-panel" aria-labelledby="bank-settings-tab" hidden={tab !== 'banks'}><LunchFlowSetup onSaved={() => { onSaved(); onClose() }} /></div>
      <div role="tabpanel" id="statement-settings-panel" aria-labelledby="statement-settings-tab" hidden={tab !== 'statements'}><StatementImport accounts={accounts} onImported={onSaved} /></div>
    </div>
  </Modal>
}
