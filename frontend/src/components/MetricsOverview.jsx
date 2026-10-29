import React from 'react';
import { Users, PhoneOutgoing, PhoneForwarded, BarChart3, Clock, ShieldCheck, Timer, AlertTriangle } from 'lucide-react';

export default function MetricsOverview({ metrics }) {
  if (!metrics) return null;

  const agentStates = metrics.agents_by_state || {};
  const availableCount = agentStates.AVAILABLE || 0;
  const dialingCount = agentStates.DIALING || 0;
  const connectedCount = agentStates.CONNECTED || 0;
  const wrapUpCount = agentStates.WRAP_UP || 0;

  return (
    <div className="metrics-grid">
      <div className="metric-card">
        <div className="metric-header">
          <span>Agents Workforce</span>
          <Users size={16} />
        </div>
        <div className="metric-value">{availableCount} / {metrics.total_agents}</div>
        <div className="metric-footer">
          {availableCount} Available • {dialingCount + connectedCount} on call • {wrapUpCount} wrap
        </div>
      </div>

      <div className="metric-card">
        <div className="metric-header">
          <span>Active Calls</span>
          <PhoneOutgoing size={16} />
        </div>
        <div className="metric-value">{metrics.active_calls}</div>
        <div className="metric-footer">
          {metrics.queued_borrowers} borrowers queued in campaign
        </div>
      </div>

      <div className="metric-card">
        <div className="metric-header">
          <span>Answer Rate</span>
          <PhoneForwarded size={16} />
        </div>
        <div className="metric-value">{metrics.answer_rate_pct}%</div>
        <div className="metric-footer">
          Historical answer likelihood
        </div>
      </div>

      <div className="metric-card">
        <div className="metric-header">
          <span>Agent Utilization</span>
          <BarChart3 size={16} />
        </div>
        <div className="metric-value">{metrics.agent_utilization_pct}%</div>
        <div className="metric-footer">
          Active agents handling calls or wrap-up
        </div>
      </div>

      <div className="metric-card">
        <div className="metric-header">
          <span>Avg Talk Time</span>
          <Clock size={16} />
        </div>
        <div className="metric-value">{metrics.average_talk_time_seconds}s</div>
        <div className="metric-footer">
          {metrics.completed_calls} completed • {metrics.failed_calls} failed
        </div>
      </div>

      <div className="metric-card">
        <div className="metric-header">
          <span>Avg Call Setup</span>
          <Timer size={16} />
        </div>
        <div className="metric-value">{metrics.average_call_setup_seconds}s</div>
        <div className="metric-footer">
          Provider reservation-to-acknowledgement
        </div>
      </div>

      <div className="metric-card">
        <div className="metric-header">
          <span>Pacing Suggestion</span>
          <ShieldCheck size={16} />
        </div>
        <div className="metric-value">{metrics.pacing_suggested_multiplier}x</div>
        <div className="metric-footer">
          Proposed calls per available agent
        </div>
      </div>

      <div className="metric-card">
        <div className="metric-header">
          <span>Primary Route</span>
          <ShieldCheck size={16} />
        </div>
        <div className="metric-value" style={{ fontSize: '1.4rem' }}>
          {metrics.primary_provider_healthy ? 'Normal' : 'Outage'}
        </div>
        <div className="metric-footer">
          {metrics.primary_provider_healthy ? 'Automated fallback ready' : 'Fallback active'}
        </div>
      </div>

      <div className="metric-card">
        <div className="metric-header">
          <span>Acceptance Uncertain</span>
          <AlertTriangle size={16} />
        </div>
        <div className="metric-value">{metrics.uncertain_provider_submissions || 0}</div>
        <div className="metric-footer">
          Retained for provider reconciliation; not retried
        </div>
      </div>
    </div>
  );
}
