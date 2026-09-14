import { mockAsk, mockAskWithStepper, INVARIANT } from './data';
import type { AskResponse, Flag, LineageItem } from '@/types';

export type { AskResponse } from '@/types';
export { INVARIANT, mockAsk, mockAskWithStepper };

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';
export const API_KEY = import.meta.env.VITE_API_KEY ?? 'ak_demo_key_12345';

// ---------------------------------------------------------------------------
// Raw backend response shape (mirrors backend/app/api_widget.py AskResponse)
// ---------------------------------------------------------------------------
interface RawAskResponse {
  answer?: string;
  confidence?: string;
  caveats?: string[];
  lineage?: Record<string, unknown> | null;
  chart?: { type?: string; title?: string; data?: { label: string; value: number }[] } | null;
  status?: string;
  flags?: string[];
  invariant?: string | null;
  plan_type?: string | null;
  confirmation_token?: string | null;
  user_message?: string | null;
  denied_reason?: string | null;
  tenant_id?: string | null;
  policy?: Record<string, unknown> | null;
}

interface ConfirmResponse {
  status: 'approved' | 'rejected';
  message: string;
  action_type?: string;
  invariant?: string;
  policy?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mapFlags(raw: string[] | undefined): Flag[] {
  return (raw ?? []).map((label, i): Flag => ({
    type: (['pii_risk', 'quota_warning', 'metric_pending', 'unknown_metric', 'rate_limit'][i % 5] as Flag['type']),
    label,
    severity: label.toLowerCase().includes('pii') || label.toLowerCase().includes('denied') ? 'critical' : 'warning',
  }));
}

/**
 * Normalise the backend lineage payload to LineageItem[].
 *
 * The backend (agent_phase4.attach_lineage) returns:
 *   { metrics_or_tools_used: string[], filters_applied: {}, notes: string }
 *
 * Older / mock shapes may return:
 *   { metric_name: "metric" | "tool" | "dataset", ... }
 *
 * We handle both so the Trust panel always renders correctly.
 */
function mapLineage(raw: Record<string, unknown> | null | undefined): LineageItem[] {
  if (!raw) return [];

  const out: LineageItem[] = [];

  // New shape: { metrics_or_tools_used: ["total_revenue", "stats_tool", ...] }
  const used = raw['metrics_or_tools_used'];
  if (Array.isArray(used)) {
    for (const name of used) {
      if (typeof name !== 'string') continue;
      // Heuristic: known tool names → 'tool', otherwise 'metric'
      const toolNames = new Set(['describe', 'trend', 'correlation', 'regression', 'stats_tool', 'trend_tool']);
      const kind: LineageItem['kind'] = toolNames.has(name) ? 'tool' : 'metric';
      out.push({ name, kind });
    }
    if (out.length > 0) return out;
  }

  // Legacy / mock shape: { "total_revenue": "metric", "stats_tool": "tool", ... }
  for (const [name, kind] of Object.entries(raw)) {
    if (typeof kind === 'string' && (kind === 'metric' || kind === 'tool' || kind === 'dataset')) {
      out.push({ name, kind });
    }
  }
  return out;
}

function mapResponse(raw: RawAskResponse): AskResponse {
  const status = raw.confirmation_token
    ? 'awaiting_confirmation'
    : raw.status === 'denied' || raw.denied_reason
      ? 'denied'
      : raw.status === 'error' || raw.status === 'resource_limit'
        ? 'error'
        : 'completed';
  const conf = (raw.confidence ?? 'n/a').toLowerCase();
  const confidence = conf === 'high' || conf === 'medium' || conf === 'low' ? conf : 'low';
  const flags = mapFlags(raw.flags);
  if (raw.denied_reason) flags.push({ type: 'unknown_metric', label: raw.denied_reason, severity: 'critical' });
  return {
    status,
    answer: raw.answer ?? raw.user_message ?? '',
    confidence,
    flags,
    lineage: mapLineage(raw.lineage ?? null),
    plan_type: (raw.plan_type ?? 'single_metric') as AskResponse['plan_type'],
    invariant: raw.invariant ?? INVARIANT,
    chart: raw.chart
      ? {
          type: raw.chart.type === 'line' ? 'line' : 'bar',
          title: raw.chart.title ?? '',
          data: raw.chart.data ?? [],
        }
      : undefined,
    caveat: raw.caveats?.[0],
    deniedReason: raw.denied_reason ?? raw.user_message ?? undefined,
    confirmationToken: raw.confirmation_token ?? null,
  };
}

// ---------------------------------------------------------------------------
// Sample CSV for auto-upload on session create
// (Mirrors samples/sample_sales_data.csv — the canonical demo dataset)
// ---------------------------------------------------------------------------
const SAMPLE_CSV = `order_id,date,region,category,sales,quantity,customer_rating
ORD-1001,2024-01-05,North,Electronics,1250.00,2,4.8
ORD-1002,2024-01-07,South,Clothing,85.50,3,4.2
ORD-1003,2024-01-10,East,Furniture,450.00,1,3.9
ORD-1004,2024-01-12,West,Electronics,890.00,1,4.5
ORD-1005,2024-01-15,North,Clothing,120.00,4,4.0
ORD-1006,2024-01-18,South,Electronics,2100.00,3,4.9
ORD-1007,2024-01-20,East,Clothing,65.00,2,3.5
ORD-1008,2024-01-22,West,Furniture,620.00,2,4.1
ORD-1009,2024-01-25,North,Furniture,310.00,1,4.3
ORD-1010,2024-01-28,South,Clothing,150.00,5,4.7
ORD-1011,2024-02-02,East,Electronics,1450.00,2,4.6
ORD-1012,2024-02-05,West,Clothing,95.00,2,4.0
ORD-1013,2024-02-08,North,Electronics,780.00,1,4.4
ORD-1014,2024-02-12,South,Furniture,890.00,3,4.2
ORD-1015,2024-02-15,East,Clothing,110.00,3,3.8
ORD-1016,2024-02-18,West,Electronics,1950.00,2,4.9
ORD-1017,2024-02-22,North,Clothing,210.00,4,4.1
ORD-1018,2024-02-25,South,Electronics,1150.00,1,4.5
ORD-1019,2024-02-27,East,Furniture,540.00,2,4.0
ORD-1020,2024-02-28,West,Clothing,175.00,3,4.3`;

let _sessionId: string | null = null;

async function ensureSession(): Promise<string | null> {
  if (!API_BASE) return null;
  if (_sessionId) return _sessionId;

  const res = await fetch(`${API_BASE}/api/v1/session`, {
    method: 'POST',
    headers: { 'X-API-Key': API_KEY, 'Content-Type': 'application/json' },
  });
  if (!res.ok) return null;
  const data = await res.json();
  _sessionId = data.session_id ?? null;

  if (_sessionId) {
    const form = new FormData();
    form.append('file', new Blob([SAMPLE_CSV], { type: 'text/csv' }), 'sample_sales_data.csv');
    form.append('session_id', _sessionId);
    await fetch(`${API_BASE}/api/v1/upload`, {
      method: 'POST',
      headers: { 'X-API-Key': API_KEY },
      body: form,
    }).catch(() => null);
  }

  return _sessionId;
}

// ---------------------------------------------------------------------------
// Error helpers — return user-friendly AskResponse for HTTP errors
// ---------------------------------------------------------------------------
function errorResponse(status: number, message: string): AskResponse {
  const flag: Flag | undefined =
    status === 401 || status === 403
      ? { type: 'unknown_metric', label: 'Access denied — check VITE_API_KEY', severity: 'critical' }
      : status === 429
        ? { type: 'quota_warning', label: 'Quota exceeded — try again later', severity: 'critical' }
        : undefined;
  return {
    status: 'error',
    answer: message,
    confidence: 'low',
    flags: flag ? [flag] : [],
    lineage: [],
    plan_type: 'single_metric',
    invariant: INVARIANT,
    deniedReason: message,
  };
}

// ---------------------------------------------------------------------------
// Public API client
// ---------------------------------------------------------------------------
export const apiClient = {
  async ask(question: string): Promise<AskResponse> {
    if (!API_BASE) return mockAsk(question);
    const sessionId = await ensureSession();
    if (!sessionId) {
      return errorResponse(0, 'Could not create session — is the backend running?');
    }
    const res = await fetch(`${API_BASE}/api/v1/ask`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
      },
      body: JSON.stringify({
        session_id: sessionId,
        question,
        dataset: null,
      }),
    });
    if (res.status === 401 || res.status === 403) {
      return errorResponse(res.status, 'Access denied — invalid or revoked API key');
    }
    if (res.status === 429) {
      return errorResponse(res.status, 'Quota exceeded — try again later');
    }
    if (!res.ok) {
      return errorResponse(res.status, `Backend error ${res.status}`);
    }
    return mapResponse(await res.json());
  },

  async askWithStepper(
    question: string,
    onStep: (steps: { label: string; status: 'done' | 'active' | 'pending' }[]) => void,
  ): Promise<AskResponse> {
    const r = await this.ask(question);
    if (r.status === 'completed') onStep([{ label: 'Synthesize', status: 'done' }]);
    return r;
  },

  /**
   * Approve or reject a pending confirmation.
   * Returns the backend confirm response, or null on network error.
   */
  async confirmAction(token: string, approve: boolean): Promise<ConfirmResponse | null> {
    if (!API_BASE) {
      // Mock mode — return a synthetic response
      return {
        status: approve ? 'approved' : 'rejected',
        message: approve ? 'Action approved.' : 'Action rejected.',
        invariant: INVARIANT,
        policy: { phase: 4, enforced: true },
      };
    }
    const res = await fetch(`${API_BASE}/api/v1/ask/confirm`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
      },
      body: JSON.stringify({ confirmation_token: token, approve }),
    });
    if (!res.ok) {
      console.error('confirmAction failed:', res.status);
      return null;
    }
    return (await res.json()) as ConfirmResponse;
  },
};
