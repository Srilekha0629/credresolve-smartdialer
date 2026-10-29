import React, { useState } from 'react';
import { FlaskConical } from 'lucide-react';

const scenarioDescriptions = {
  A: '20% answer rate, 120-second average talk time',
  B: '50% answer rate, 90-second average talk time',
  C: '70% answer rate, 180-second average talk time',
  D: 'Changing answer rate and talk time, Provider B outage/fallback and webhook faults',
};

export default function ScenarioRunner({ onRunScenario, result, loading }) {
  const [scenario, setScenario] = useState('A');

  return (
    <section className="section-card">
      <div className="section-title">
        <FlaskConical size={18} />
        <span>Deterministic Scenario Simulation</span>
        <span className="badge badge-blue">SIMULATED</span>
      </div>
      <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
        Runs the selected scenario through the dialer, provider adapter, and provider-event processor.
        This resets the demo dataset; results are simulated and are not live carrier statistics.
      </p>
      <div style={{ display: 'flex', gap: '0.65rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <select
          aria-label="Simulation scenario"
          value={scenario}
          onChange={(event) => setScenario(event.target.value)}
          disabled={loading}
          style={{
            padding: '0.55rem',
            borderRadius: '6px',
            background: 'var(--bg-tertiary)',
            border: '1px solid var(--border-color)',
            color: 'white',
          }}
        >
          {Object.entries(scenarioDescriptions).map(([key, description]) => (
            <option key={key} value={key}>Scenario {key}: {description}</option>
          ))}
        </select>
        <button
          className="btn btn-primary"
          onClick={() => onRunScenario(scenario)}
          disabled={loading}
        >
          Run Scenario {scenario}
        </button>
      </div>
      {result && (
        <div style={{ marginTop: '0.85rem', fontSize: '0.82rem', color: 'var(--text-muted)' }}>
          <strong>Last run: Scenario {result.scenario}</strong> — {result.description}
          {result.cycle && (
            <div>
              Selected mode: {result.cycle.mode}; calls initiated: {result.cycle.calls_initiated};
              {' '}webhook results: {result.event_results?.processed || 0} processed,
              {' '}{result.event_results?.ignored_duplicate || 0} duplicate(s) ignored,
              {' '}{result.event_results?.rejected || 0} rejected.
            </div>
          )}
          {result.phases?.map((phase) => (
            <div key={phase.phase}>
              Phase {phase.phase}: {phase.inputs.answer_rate * 100}% answer-rate input,
              {' '}mode {phase.cycle.mode}, {phase.cycle.calls_initiated} call(s) initiated;
              {' '}provider events {phase.event_results.processed} processed,
              {' '}{phase.event_results.ignored_duplicate} duplicate(s) ignored,
              {' '}{phase.event_results.rejected} rejected.
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
