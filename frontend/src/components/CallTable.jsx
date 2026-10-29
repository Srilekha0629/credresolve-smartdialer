import React from 'react';
import { Phone, PhoneCall, PhoneOff, Check, BellRing } from 'lucide-react';

const CALL_STATE_BADGE_CLASS = {
  QUEUED: 'badge-gray',
  RESERVED: 'badge-blue',
  INITIATED: 'badge-blue',
  RINGING: 'badge-amber',
  ANSWERED: 'badge-purple',
  CONNECTED: 'badge-green',
  COMPLETED: 'badge-gray',
  FAILED: 'badge-red',
  CANCELLED: 'badge-red',
};

export default function CallTable({ calls, onProgressCall, loading }) {
  if (!calls || calls.length === 0) {
    return (
      <div className="section-card">
        <div className="section-title">
          <Phone size={18} />
          <span>Active & Recent Calls</span>
        </div>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          No calls placed yet. Run a progressive or predictive cycle to initiate outbound calls.
        </p>
      </div>
    );
  }

  return (
    <div className="section-card">
      <div className="section-title">
        <Phone size={18} />
        <span>Active & Recent Calls ({calls.length})</span>
      </div>

      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Call ID</th>
              <th>Borrower</th>
              <th>Phone</th>
              <th>Assigned Agent</th>
              <th>Provider</th>
              <th>State</th>
              <th>Duration</th>
              <th>Simulate Event</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((call) => {
              const badgeClass = CALL_STATE_BADGE_CLASS[call.state] || 'badge-gray';

              return (
                <tr key={call.id}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{call.id}</td>
                  <td><strong>{call.borrower_name}</strong></td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{call.borrower_phone}</td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
                    {call.agent_id || <span style={{ color: 'var(--text-dim)' }}>Unassigned</span>}
                  </td>
                  <td>
                    <span className="badge badge-gray" style={{ fontSize: '0.68rem' }}>
                      {call.provider}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${badgeClass}`}>{call.state}</span>
                  </td>
                  <td>{call.duration_seconds > 0 ? `${Math.round(call.duration_seconds)}s` : '—'}</td>
                  <td>
                    <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                      {call.state === 'INITIATED' && (
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => onProgressCall(call.id, 'RINGING')}
                          disabled={loading}
                          title="Simulate handset ringing event"
                        >
                          <BellRing size={12} /> Ringing
                        </button>
                      )}

                      {(call.state === 'INITIATED' || call.state === 'RINGING') && (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => onProgressCall(call.id, 'CONNECTED')}
                          disabled={loading}
                          title="Simulate borrower answering and bridging to agent"
                        >
                          <PhoneCall size={12} /> Bridge
                        </button>
                      )}

                      {(call.state === 'CONNECTED' || call.state === 'ANSWERED') && (
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => onProgressCall(call.id, 'COMPLETED')}
                          disabled={loading}
                          title="Simulate normal call termination and start agent wrap-up"
                        >
                          <PhoneOff size={12} /> Hang Up
                        </button>
                      )}

                      {call.state !== 'COMPLETED' && call.state !== 'FAILED' && call.state !== 'CANCELLED' && (
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => onProgressCall(call.id, 'FAILED', 'Simulated network drop')}
                          disabled={loading}
                          title="Simulate network failure / line drop"
                        >
                          Fail
                        </button>
                      )}

                      {call.state === 'COMPLETED' && (
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                          <Check size={12} style={{ display: 'inline', marginRight: '3px' }} />
                          Completed
                        </span>
                      )}

                      {call.state === 'FAILED' && (
                        <span style={{ fontSize: '0.75rem', color: 'var(--accent-red)' }}>
                          {call.error_reason || 'Failed'}
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
