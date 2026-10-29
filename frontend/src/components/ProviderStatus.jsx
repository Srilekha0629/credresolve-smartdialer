import React from 'react';
import { Server, Radio, AlertTriangle, ShieldCheck, Check } from 'lucide-react';

export default function ProviderStatus({ providers, onConfigureProviderB, onSetPrimaryProvider, loading }) {
  if (!providers || providers.length < 2) return null;

  const providerA = providers.find((p) => p.name === 'PROVIDER_A') || providers[0];
  const providerB = providers.find((p) => p.name === 'PROVIDER_B') || providers[1];
  const simModes = providerB.simulation_modes || {};

  const handleSimToggle = (key) => {
    onConfigureProviderB({ [key]: !simModes[key] });
  };

  const handleUnhealthyToggle = () => {
    onConfigureProviderB({ manual_unhealthy: providerB.is_healthy });
  };

  return (
    <div className="section-card">
      <div className="section-title">
        <Radio size={18} />
        <span>Mock Telecom Providers & Resilience Gateway</span>
      </div>

      <div className="two-col-grid" style={{ gap: '1rem' }}>
        {/* Provider A Card */}
        <div
          style={{
            background: 'var(--bg-tertiary)',
            padding: '1rem',
            borderRadius: '8px',
            border: providerA.is_primary ? '1px solid var(--accent-blue)' : '1px solid var(--border-color)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Server size={16} />
              <strong style={{ fontSize: '0.9rem' }}>Provider A (Tier 1 Direct)</strong>
            </div>
            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
              {providerA.is_primary && <span className="badge badge-blue">PRIMARY</span>}
              <span className={`badge ${providerA.is_healthy ? 'badge-green' : 'badge-red'}`}>
                {providerA.is_healthy ? 'HEALTHY' : 'OUTAGE'}
              </span>
            </div>
          </div>

          <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
            Fast, high-uptime reliable telecom carrier route. Fallback target.
          </p>

          <div style={{ fontSize: '0.78rem', color: 'var(--text-dim)', display: 'flex', gap: '1rem', marginBottom: '0.75rem' }}>
            <span>Calls Placed: <strong>{providerA.total_calls}</strong></span>
            <span>Failures: <strong>{providerA.total_failures}</strong></span>
          </div>

          {!providerA.is_primary && (
            <button
              className="btn btn-outline btn-sm"
              onClick={() => onSetPrimaryProvider('PROVIDER_A')}
              disabled={loading}
            >
              Make Primary Route
            </button>
          )}
        </div>

        {/* Provider B Card (Flaky / Simulated) */}
        <div
          style={{
            background: 'var(--bg-tertiary)',
            padding: '1rem',
            borderRadius: '8px',
            border: providerB.is_primary ? '1px solid var(--accent-purple)' : '1px solid var(--border-color)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <AlertTriangle size={16} className="text-amber-400" />
              <strong style={{ fontSize: '0.9rem' }}>Provider B (Flaky / Fault Injection)</strong>
            </div>
            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
              {providerB.is_primary && <span className="badge badge-purple">PRIMARY</span>}
              <span className={`badge ${providerB.is_healthy ? 'badge-green' : 'badge-red'}`}>
                {providerB.is_healthy ? 'HEALTHY' : 'UNHEALTHY'}
              </span>
            </div>
          </div>

          <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '0.6rem' }}>
            Timeout and outage affect normal Provider B call setup. Duplicate and out-of-order
            webhook generation is scenario-only (Scenario D).
          </p>

          {/* Fault Injection Toggles */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.4rem', fontSize: '0.75rem', marginBottom: '0.75rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={!!simModes.simulate_timeout}
                onChange={() => handleSimToggle('simulate_timeout')}
              />
              Simulate Timeout (504)
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={!!simModes.simulate_failure}
                onChange={() => handleSimToggle('simulate_failure')}
              />
              Simulate Failure (503)
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={!!simModes.simulate_duplicate}
                onChange={() => handleSimToggle('simulate_duplicate')}
              />
              Simulate Duplicates
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={!!simModes.simulate_out_of_order}
                onChange={() => handleSimToggle('simulate_out_of_order')}
              />
              Out-of-Order Webhooks
            </label>
          </div>
          <p style={{ fontSize: '0.72rem', color: 'var(--text-dim)', margin: '-0.3rem 0 0.75rem' }}>
            Duplicate and out-of-order toggles are consumed by Scenario D; routine dial runs do not
            emit provider callbacks automatically.
          </p>

          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {!providerB.is_primary ? (
              <button
                className="btn btn-outline btn-sm"
                onClick={() => onSetPrimaryProvider('PROVIDER_B')}
                disabled={loading}
              >
                Set As Primary Route
              </button>
            ) : null}

            <button
              className="btn btn-outline btn-sm"
              onClick={handleUnhealthyToggle}
              disabled={loading}
              title="Force trip or restore provider health"
            >
              {providerB.is_healthy ? 'Simulate Outage' : 'Restore Health'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
