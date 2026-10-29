import React, { useState } from 'react';
import { Play, Sparkles, Shield, Sliders } from 'lucide-react';

export default function DialerControls({ onRunProgressive, onRunPredictive, loading, availableAgents }) {
  const [maxCalls, setMaxCalls] = useState('');
  const [targetAnswerRate, setTargetAnswerRate] = useState('0.40');
  const [maxPacingRatio, setMaxPacingRatio] = useState('2.0');
  const [allowFallback, setAllowFallback] = useState(true);

  const handleProgressiveSubmit = (e) => {
    e.preventDefault();
    const count = maxCalls.trim() ? parseInt(maxCalls, 10) : null;
    onRunProgressive(count);
  };

  const handlePredictiveSubmit = (e) => {
    e.preventDefault();
    onRunPredictive(targetAnswerRate, maxPacingRatio, allowFallback);
  };

  return (
    <div className="two-col-grid">
      {/* Progressive Dialer Panel */}
      <div className="section-card">
        <div className="section-title">
          <Play size={18} className="text-blue-400" />
          <span>Progressive Dialer Mode</span>
          <span className="badge badge-blue">1:1 Safety</span>
        </div>
        <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
          Reserves exactly one AVAILABLE agent for each outbound call. Never dials more calls than safe agent availability. Concurrency locked.
        </p>

        <form onSubmit={handleProgressiveSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          <div>
            <label style={{ fontSize: '0.78rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>
              Max Calls Cap (Optional, blank = all available agents):
            </label>
            <input
              type="number"
              min="1"
              max="20"
              placeholder={`Max safe: ${availableAgents}`}
              value={maxCalls}
              onChange={(e) => setMaxCalls(e.target.value)}
              style={{
                width: '100%',
                padding: '0.5rem 0.75rem',
                borderRadius: '6px',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                color: 'white',
                fontSize: '0.85rem',
              }}
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || availableAgents === 0}
            style={{ width: '100%' }}
          >
            <Play size={15} />
            Run Progressive Dialer ({availableAgents} agents ready)
          </button>
        </form>
      </div>

      {/* Predictive Dialer Panel */}
      <div className="section-card">
        <div className="section-title">
          <Sparkles size={18} className="text-purple-400" />
          <span>Predictive Pacing Engine</span>
          <span className="badge badge-purple">Heuristic Pacing</span>
        </div>
        <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
          Suggests call volume based on answer rate, wrap-up times, and agent availability. Strictly filtered through the separate Safety Controller.
        </p>

        <form onSubmit={handlePredictiveSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div>
              <label style={{ fontSize: '0.78rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>
                Answer Rate Target:
              </label>
              <select
                value={targetAnswerRate}
                onChange={(e) => setTargetAnswerRate(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  borderRadius: '6px',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  color: 'white',
                  fontSize: '0.85rem',
                }}
              >
                <option value="0.20">20% (Low - overdial)</option>
                <option value="0.40">40% (Standard)</option>
                <option value="0.60">60% (High answer)</option>
                <option value="0.80">80% (Very high)</option>
              </select>
            </div>

            <div>
              <label style={{ fontSize: '0.78rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>
                Max Pacing Cap:
              </label>
              <select
                value={maxPacingRatio}
                onChange={(e) => setMaxPacingRatio(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  borderRadius: '6px',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  color: 'white',
                  fontSize: '0.85rem',
                }}
              >
                <option value="1.5">1.5x Overdial</option>
                <option value="2.0">2.0x Overdial</option>
                <option value="3.0">3.0x Overdial</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            <input
              type="checkbox"
              id="fallbackToggle"
              checked={allowFallback}
              onChange={(e) => setAllowFallback(e.target.checked)}
              style={{ cursor: 'pointer' }}
            />
            <label htmlFor="fallbackToggle" style={{ cursor: 'pointer' }}>
              Safety Fallback: automatically revert to progressive 1:1 if answer rate drops below 15%
            </label>
          </div>

          <button
            type="submit"
            className="btn btn-purple"
            disabled={loading || availableAgents === 0}
            style={{ width: '100%' }}
          >
            <Sparkles size={15} />
            Run Predictive Cycle (via Safety Gate)
          </button>
        </form>
      </div>
    </div>
  );
}
