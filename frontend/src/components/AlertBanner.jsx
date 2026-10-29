import React from 'react';
import { AlertCircle, CheckCircle2, X } from 'lucide-react';

export default function AlertBanner({ alert, onDismiss }) {
  if (!alert || !alert.message) return null;

  const isSuccess = alert.type === 'success';

  return (
    <div className={`alert ${isSuccess ? 'alert-success' : 'alert-error'}`}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
        {isSuccess ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
        <span>{alert.message}</span>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer' }}
        >
          <X size={16} />
        </button>
      )}
    </div>
  );
}
