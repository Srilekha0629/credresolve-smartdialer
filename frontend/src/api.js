// API Client for SmartDialer Backend

const API_BASE = 'http://localhost:8000';
const createIdempotencyKey = () =>
  globalThis.crypto?.randomUUID?.() ||
  `dial-${Date.now()}-${Math.random().toString(16).slice(2)}`;

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  try {
    const res = await fetch(url, { ...options, headers });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || data.message || `Request failed with status ${res.status}`);
    }
    return data;
  } catch (err) {
    console.error(`API Error on ${endpoint}:`, err);
    throw err;
  }
}

export const api = {
  getHealth: () => request('/health'),
  getMetrics: () => request('/metrics'),
  getAgents: () => request('/agents'),
  getBorrowers: () => request('/borrowers'),
  getCalls: () => request('/calls'),
  getProviders: () => request('/providers'),

  runProgressive: (maxCalls = null, idempotencyKey = createIdempotencyKey()) =>
    request('/dialer/progressive/run', {
      method: 'POST',
      body: JSON.stringify({ max_calls: maxCalls }),
      headers: { 'Idempotency-Key': idempotencyKey },
    }),

  runPredictive: (targetAnswerRate = null, maxPacingRatio = 2.0, allowFallback = true, idempotencyKey = createIdempotencyKey()) =>
    request('/dialer/predictive/run', {
      method: 'POST',
      body: JSON.stringify({
        target_answer_rate: targetAnswerRate ? parseFloat(targetAnswerRate) : null,
        max_pacing_ratio: parseFloat(maxPacingRatio),
        allow_fallback: allowFallback,
      }),
      headers: { 'Idempotency-Key': idempotencyKey },
    }),

  sendProviderEvent: (eventPayload) =>
    request('/events/provider', {
      method: 'POST',
      body: JSON.stringify(eventPayload),
    }),

  progressCall: (callId, eventType, reason = null) =>
    request(`/calls/${callId}/progress`, {
      method: 'POST',
      body: JSON.stringify({ event_type: eventType, reason }),
    }),

  updateAgentState: (agentId, state) =>
    request(`/agents/${agentId}/state`, {
      method: 'POST',
      body: JSON.stringify({ state }),
    }),

  configureProviderB: (config) =>
    request('/providers/configure', {
      method: 'POST',
      body: JSON.stringify(config),
    }),

  setPrimaryProvider: (provider) =>
    request('/providers/primary', {
      method: 'POST',
      body: JSON.stringify({ provider }),
    }),

  resetSimulation: () =>
    request('/simulation/reset', {
      method: 'POST',
    }),

  runScenario: (scenario) =>
    request(`/simulation/scenarios/${encodeURIComponent(scenario)}`, {
      method: 'POST',
    }),
};
