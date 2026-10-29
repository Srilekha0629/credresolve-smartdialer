import React, { useState, useEffect, useCallback } from 'react';
import { api } from './api';
import Header from './components/Header';
import MetricsOverview from './components/MetricsOverview';
import DialerControls from './components/DialerControls';
import ScenarioRunner from './components/ScenarioRunner';
import ProviderStatus from './components/ProviderStatus';
import AgentTable from './components/AgentTable';
import CallTable from './components/CallTable';
import BorrowerTable from './components/BorrowerTable';
import AlertBanner from './components/AlertBanner';

export default function App() {
  const [metrics, setMetrics] = useState(null);
  const [agents, setAgents] = useState([]);
  const [borrowers, setBorrowers] = useState([]);
  const [calls, setCalls] = useState([]);
  const [providers, setProviders] = useState([]);
  const [isHealthy, setIsHealthy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [alert, setAlert] = useState(null);
  const [scenarioResult, setScenarioResult] = useState(null);

  const fetchAllData = useCallback(async () => {
    try {
      const [m, a, b, c, p] = await Promise.all([
        api.getMetrics(),
        api.getAgents(),
        api.getBorrowers(),
        api.getCalls(),
        api.getProviders(),
      ]);
      setMetrics(m);
      setAgents(a);
      setBorrowers(b);
      setCalls(c);
      setProviders(p);
      setIsHealthy(true);
      return true;
    } catch (err) {
      console.warn('Backend polling error:', err.message);
      setIsHealthy(false);
      return false;
    }
  }, []);

  useEffect(() => {
    fetchAllData();
    const interval = setInterval(fetchAllData, 3000);
    return () => clearInterval(interval);
  }, [fetchAllData]);

  const showAlert = (message, type = 'info') => {
    setAlert({ message, type });
    setTimeout(() => {
      setAlert((curr) => (curr && curr.message === message ? null : curr));
    }, 6000);
  };

  const handleRefresh = async () => {
    setLoading(true);
    try {
      if (await fetchAllData()) {
        showAlert('System state refreshed.', 'success');
      } else {
        showAlert('Refresh failed: the backend did not return all dashboard data.', 'error');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    if (!window.confirm('Reset the demo database and clear current calls, events, and metrics?')) {
      return;
    }
    setLoading(true);
    try {
      const res = await api.resetSimulation();
      await fetchAllData();
      showAlert(res.message || 'Simulation reset to seed state.', 'success');
    } catch (err) {
      showAlert(`Reset failed: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleRunProgressive = async (maxCalls) => {
    setLoading(true);
    try {
      const res = await api.runProgressive(maxCalls);
      await fetchAllData();
      if (res.calls_initiated > 0) {
        showAlert(
          `Progressive dialer successfully initiated ${res.calls_initiated} calls. Notes: ${res.notes || 'Safe allocation approved.'}`,
          'success'
        );
      } else {
        showAlert(
          `Progressive dialer initiated 0 calls. Notes: ${res.notes || 'No available capacity.'}`,
          'error'
        );
      }
    } catch (err) {
      showAlert(`Progressive dialer error: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleRunPredictive = async (targetAnswerRate, maxPacingRatio, allowFallback) => {
    setLoading(true);
    try {
      const res = await api.runPredictive(targetAnswerRate, maxPacingRatio, allowFallback);
      await fetchAllData();
      if (res.calls_initiated > 0) {
        showAlert(
          `Predictive cycle placed ${res.calls_initiated} calls (proposed: ${res.proposed_calls}, approved: ${res.safe_approved_calls}). Notes: ${res.notes}`,
          'success'
        );
      } else {
        showAlert(`Predictive cycle placed 0 calls. Notes: ${res.notes}`, 'error');
      }
    } catch (err) {
      showAlert(`Predictive dialer error: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleRunScenario = async (scenario) => {
    setLoading(true);
    try {
      const result = await api.runScenario(scenario);
      setScenarioResult(result);
      await fetchAllData();
      showAlert(
        `Scenario ${scenario} completed. All displayed outcomes are simulated.`,
        'success'
      );
    } catch (err) {
      showAlert(`Scenario failed: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateAgentState = async (agentId, newState) => {
    setLoading(true);
    try {
      await api.updateAgentState(agentId, newState);
      await fetchAllData();
      showAlert(`Agent ${agentId} transitioned to ${newState}.`, 'success');
    } catch (err) {
      showAlert(`Failed to update agent: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleProgressCall = async (callId, eventType, reason) => {
    setLoading(true);
    try {
      const res = await api.progressCall(callId, eventType, reason);
      await fetchAllData();
      if (res.success) {
        showAlert(`Call ${callId} transitioned to ${res.current_call_state}.`, 'success');
      } else {
        showAlert(`Transition rejected: ${res.message}`, 'error');
      }
    } catch (err) {
      showAlert(`Call progression failed: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleConfigureProviderB = async (config) => {
    setLoading(true);
    try {
      await api.configureProviderB(config);
      await fetchAllData();
      showAlert('Provider B configuration updated.', 'success');
    } catch (err) {
      showAlert(`Provider update failed: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleSetPrimaryProvider = async (provider) => {
    setLoading(true);
    try {
      await api.setPrimaryProvider(provider);
      await fetchAllData();
      showAlert(`Primary route switched to ${provider}.`, 'success');
    } catch (err) {
      showAlert(`Failed to set primary provider: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const availableAgentsCount = agents.filter(
    (a) => a.state === 'AVAILABLE' && !a.current_call_id
  ).length;

  return (
    <div className="app-container">
      <Header
        isHealthy={isHealthy}
        onRefresh={handleRefresh}
        onReset={handleReset}
        loading={loading}
      />

      <AlertBanner alert={alert} onDismiss={() => setAlert(null)} />

      <MetricsOverview metrics={metrics} />

      <DialerControls
        onRunProgressive={handleRunProgressive}
        onRunPredictive={handleRunPredictive}
        loading={loading}
        availableAgents={availableAgentsCount}
      />

      <ScenarioRunner
        onRunScenario={handleRunScenario}
        result={scenarioResult}
        loading={loading}
      />

      <ProviderStatus
        providers={providers}
        onConfigureProviderB={handleConfigureProviderB}
        onSetPrimaryProvider={handleSetPrimaryProvider}
        loading={loading}
      />

      <div className="two-col-grid">
        <AgentTable
          agents={agents}
          onUpdateAgentState={handleUpdateAgentState}
          loading={loading}
        />
        <CallTable
          calls={calls}
          onProgressCall={handleProgressCall}
          loading={loading}
        />
      </div>

      <BorrowerTable borrowers={borrowers} />
    </div>
  );
}
