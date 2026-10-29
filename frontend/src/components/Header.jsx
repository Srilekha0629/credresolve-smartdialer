import React from 'react';
import { PhoneCall, RotateCcw, RefreshCw, Activity } from 'lucide-react';

export default function Header({ isHealthy, onRefresh, onReset, loading }) {
  return (
    <header className="header-card">
      <div className="brand-wrapper">
        <div className="brand-icon">
          <PhoneCall size={22} />
        </div>
        <div>
          <h1 className="brand-title">CredResolve SmartDialer</h1>
          <p className="brand-subtitle">
            Progressive & Predictive Outbound Dialing Engine • Concurrency Safe
          </p>
        </div>
      </div>

      <div className="header-actions">
        <div
          className={`badge ${isHealthy ? 'badge-green' : 'badge-red'}`}
          title="Backend API Connection Status"
        >
          <Activity size={12} />
          {isHealthy ? 'API Online' : 'Connecting...'}
        </div>

        <button
          className="btn btn-outline btn-sm"
          onClick={onRefresh}
          disabled={loading}
          title="Refresh live metrics and tables"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>

        <button
          className="btn btn-secondary btn-sm"
          onClick={onReset}
          disabled={loading}
          title="Reset database to seed agents & borrowers"
        >
          <RotateCcw size={14} />
          Reset Simulation
        </button>
      </div>
    </header>
  );
}
