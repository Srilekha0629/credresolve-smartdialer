import React from 'react';
import { UserCheck, Coffee, Power, PlayCircle } from 'lucide-react';

const STATE_BADGE_CLASS = {
  AVAILABLE: 'badge-green',
  RESERVED: 'badge-blue',
  DIALING: 'badge-amber',
  CONNECTED: 'badge-purple',
  WRAP_UP: 'badge-amber',
  PAUSED: 'badge-gray',
  OFFLINE: 'badge-red',
};

export default function AgentTable({ agents, onUpdateAgentState, loading }) {
  if (!agents) return null;

  return (
    <div className="section-card">
      <div className="section-title">
        <UserCheck size={18} />
        <span>Agent Workforce ({agents.length})</span>
      </div>

      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Agent ID</th>
              <th>Name</th>
              <th>Current State</th>
              <th>Active Call</th>
              <th>Calls Handled</th>
              <th>Total Talk Time</th>
              <th>Quick Actions</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((agt) => {
              const badgeClass = STATE_BADGE_CLASS[agt.state] || 'badge-gray';

              return (
                <tr key={agt.id}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{agt.id}</td>
                  <td><strong>{agt.name}</strong></td>
                  <td>
                    <span className={`badge ${badgeClass}`}>{agt.state}</span>
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                    {agt.current_call_id || <span style={{ color: 'var(--text-dim)' }}>—</span>}
                  </td>
                  <td>{agt.total_calls_handled}</td>
                  <td>{Math.round(agt.total_talk_time_seconds)}s</td>
                  <td>
                    <div style={{ display: 'flex', gap: '0.35rem' }}>
                      {agt.state === 'AVAILABLE' && (
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => onUpdateAgentState(agt.id, 'PAUSED')}
                          disabled={loading}
                          title="Take a break (PAUSE)"
                        >
                          <Coffee size={12} /> Pause
                        </button>
                      )}

                      {agt.state === 'PAUSED' && (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => onUpdateAgentState(agt.id, 'AVAILABLE')}
                          disabled={loading}
                          title="Resume to AVAILABLE"
                        >
                          <PlayCircle size={12} /> Resume
                        </button>
                      )}

                      {agt.state === 'OFFLINE' && (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => onUpdateAgentState(agt.id, 'AVAILABLE')}
                          disabled={loading}
                          title="Log in to AVAILABLE"
                        >
                          <Power size={12} /> Log In
                        </button>
                      )}

                      {agt.state === 'WRAP_UP' && (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => onUpdateAgentState(agt.id, 'AVAILABLE')}
                          disabled={loading}
                          title="Finish wrap-up and become AVAILABLE"
                        >
                          Done Wrap
                        </button>
                      )}

                      {agt.state === 'AVAILABLE' && (
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => onUpdateAgentState(agt.id, 'OFFLINE')}
                          disabled={loading}
                          title="Log off"
                        >
                          Log Off
                        </button>
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
