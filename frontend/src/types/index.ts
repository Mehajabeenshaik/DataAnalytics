export type Confidence = 'high' | 'medium' | 'low';
export type PlanType =
  | 'single_metric'
  | 'stats_tool'
  | 'trend_tool'
  | 'describe_data'
  | 'multi_metric'
  | 'confirmation_required';

export type AskStatus =
  | 'empty'
  | 'loading'
  | 'completed'
  | 'awaiting_confirmation'
  | 'denied'
  | 'error';

export interface Flag {
  type: 'pii_risk' | 'quota_warning' | 'metric_pending' | 'unknown_metric' | 'rate_limit';
  label: string;
  severity: 'warning' | 'critical';
}

export interface LineageItem {
  name: string;
  kind: 'metric' | 'tool' | 'dataset';
}

export interface ChartDatum {
  label: string;
  value: number;
}

export interface AskResponse {
  status: 'completed' | 'awaiting_confirmation' | 'denied' | 'error';
  answer: string;
  confidence: Confidence;
  flags: Flag[];
  lineage: LineageItem[];
  plan_type: PlanType;
  invariant: string;
  chart?: {
    type: 'bar' | 'line';
    title: string;
    data: ChartDatum[];
  };
  keyNumbers?: { label: string; value: string }[];
  caveat?: string;
  planSummary?: string;
  deniedReason?: string;
  steps?: { label: string; status: 'done' | 'active' | 'pending' }[];
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  response?: AskResponse;
  timestamp: number;
}

export interface HistoryEntry {
  id: string;
  question: string;
  timestamp: number;
  confidence: Confidence | null;
  planType: PlanType | null;
  flags: Flag[];
  tenant: string;
}

export interface Metric {
  id: string;
  name: string;
  description: string;
  synonyms: string[];
  status: 'Approved' | 'Pending';
  dataType: 'number' | 'currency' | 'percent' | 'date';
  sourceDataset: string;
  formula?: string;
  createdAt: number;
}

export interface Dataset {
  id: string;
  name: string;
  description: string;
  columns: number;
  rows: number;
  piiMasked: boolean;
  status: 'Active' | 'Syncing' | 'Error';
  lastUpdated: number;
  tags: string[];
}

export interface AuditEntry {
  id: string;
  time: number;
  tenant: string;
  question: string;
  planType: PlanType;
  confidence: Confidence;
  flags: Flag[];
  claimedTools: string[];
  observedTools: string[];
  hasMismatch: boolean;
  userId: string;
}

export interface Tenant {
  id: string;
  name: string;
  status: 'Active' | 'Suspended' | 'Provisioning';
  userCount: number;
  createdAt: number;
}

export interface ApiKey {
  id: string;
  label: string;
  prefix: string;
  createdAt: number;
  lastUsed: number | null;
  status: 'Active' | 'Revoked';
}

export interface User {
  id: string;
  email: string;
  displayName: string;
  role: 'admin' | 'analyst' | 'viewer';
  tenantId: string;
  avatarColor: string;
}

export type PageId =
  | 'ask'
  | 'history'
  | 'metrics'
  | 'datasets'
  | 'audit'
  | 'admin'
  | 'settings';

export interface SystemHealthStatus {
  endpoint: string;
  status: 'OK' | 'Degraded' | 'Down';
  detail: string;
  phase: string;
  isolation: boolean;
  invariantSnippet: string;
}
