import React, { useState } from 'react';
import { User, ChevronDown, ChevronUp } from 'lucide-react';

export default function BorrowerTable({ borrowers }) {
  const [collapsed, setCollapsed] = useState(false);

  if (!borrowers || borrowers.length === 0) return null;

  const queuedCount = borrowers.filter((b) => b.status === 'QUEUED').length;

  return (
    <div className="section-card">
      <div
        className="section-title"
        style={{ justifyContent: 'space-between', cursor: 'pointer', userSelect: 'none' }}
        onClick={() => setCollapsed(!collapsed)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <User size={18} />
          <span>Outbound Campaign Queue ({borrowers.length} Borrowers • {queuedCount} Queued)</span>
        </div>
        <button className="btn btn-outline btn-sm">
          {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>
      </div>

      {!collapsed && (
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Borrower ID</th>
                <th>Name</th>
                <th>Phone</th>
                <th>Outstanding Balance</th>
                <th>Status</th>
                <th>Attempts</th>
                <th>Last Call ID</th>
              </tr>
            </thead>
            <tbody>
              {borrowers.map((bor) => {
                let badgeClass = 'badge-gray';
                if (bor.status === 'QUEUED') badgeClass = 'badge-blue';
                if (bor.status === 'DIALING') badgeClass = 'badge-amber';
                if (bor.status === 'COMPLETED') badgeClass = 'badge-green';
                if (bor.status === 'FAILED') badgeClass = 'badge-red';

                return (
                  <tr key={bor.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{bor.id}</td>
                    <td>{bor.name}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{bor.phone}</td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>${bor.debt_amount.toFixed(2)}</td>
                    <td>
                      <span className={`badge ${badgeClass}`}>{bor.status}</span>
                    </td>
                    <td>{bor.calls_attempted}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                      {bor.last_call_id || <span style={{ color: 'var(--text-dim)' }}>—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
