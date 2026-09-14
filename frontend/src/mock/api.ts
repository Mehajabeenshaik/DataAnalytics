import { mockAsk, mockAskWithStepper, INVARIANT } from './data';
import type { AskResponse, Flag, LineageItem } from '@/types';

export type { AskResponse } from '@/types';
export { INVARIANT, mockAsk, mockAskWithStepper };

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';
export const API_KEY = import.meta.env.VITE_API_KEY ?? 'ak_demo_key_12345';

interface RawAskResponse {
  answer?: string;
  confidence?: string;
  caveats?: string[];
  lineage?: Record<string, unknown>;
  chart?: { type?: string; title?: string; data?: { label: string; value: number }[] } | null;
  status?: string;
  flags?: string[];
  invariant?: string | null;
  plan_type?: string | null;
  confirmation_token?: string | null;
  user_message?: string | null;
  denied_reason?: string | null;
  tenant_id?: string | null;
}

function mapFlags(raw: string[] | undefined): Flag[] {
  return (raw ?? []).map((label, i): Flag => ({
    type: (['pii_risk', 'quota_warning', 'metric_pending', 'unknown_metric', 'rate_limit'][i % 5] as Flag['type']),
    label,
    severity: label.toLowerCase().includes('pii') || label.toLowerCase().includes('denied') ? 'critical' : 'warning',
  }));
}

function mapLineage(raw: Record<string, unknown> | undefined): LineageItem[] {
  if (!raw) return [];
  const out: LineageItem[] = [];
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
      : raw.status === 'error'
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
    lineage: mapLineage(raw.lineage),
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
  };
}

const SAMPLE_CSV = `month,revenue,units
Jan,12000,150
Feb,15000,180
Mar,11000,140
Apr,17000,210
May,13000,160
Jun,16000,200`;

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

export const apiClient = {
  async ask(question: string): Promise<AskResponse> {
    if (!API_BASE) return mockAsk(question);
    const sessionId = await ensureSession();
    if (!sessionId) {
      return { status: 'error', answer: 'Could not create session', confidence: 'low', flags: [], lineage: [], plan_type: 'single_metric', invariant: INVARIANT };
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
    if (!res.ok) {
      return { status: 'error', answer: `Backend error ${res.status}`, confidence: 'low', flags: [], lineage: [], plan_type: 'single_metric', invariant: INVARIANT };
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
};
