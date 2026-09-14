import type {
  AskResponse,
  AuditEntry,
  Dataset,
  HistoryEntry,
  Metric,
  Tenant,
  ApiKey,
  User,
  SystemHealthStatus,
} from '@/types';

const API_BASE = 'http://localhost:8001';

export const tenants: Tenant[] = [
  { id: 't1', name: 'Acme Analytics', status: 'Active', userCount: 12, createdAt: Date.now() - 86400000 * 120 },
  { id: 't2', name: 'Demo Tenant', status: 'Active', userCount: 5, createdAt: Date.now() - 86400000 * 60 },
  { id: 't3', name: 'Staging Corp', status: 'Provisioning', userCount: 0, createdAt: Date.now() - 86400000 * 2 },
];

export const users: User[] = [
  {
    id: 'u1',
    email: 'admin@acme.co',
    displayName: 'Alex Chen',
    role: 'admin',
    tenantId: 't1',
    avatarColor: '#4f46e5',
  },
  {
    id: 'u2',
    email: 'analyst@demo.com',
    displayName: 'Dana Lee',
    role: 'analyst',
    tenantId: 't2',
    avatarColor: '#0d9488',
  },
];

export const metrics: Metric[] = [
  {
    id: 'm1',
    name: 'total_revenue',
    description: 'Sum of all order amounts including tax and shipping',
    synonyms: ['revenue', 'sales', 'gross income', 'topline'],
    status: 'Approved',
    dataType: 'currency',
    sourceDataset: 'Sales CSV',
    formula: 'SUM(orders.total_amount)',
    createdAt: Date.now() - 86400000 * 90,
  },
  {
    id: 'm2',
    name: 'order_count',
    description: 'Count of all placed orders',
    synonyms: ['orders', 'number of orders', 'order volume'],
    status: 'Approved',
    dataType: 'number',
    sourceDataset: 'Sales CSV',
    formula: 'COUNT(orders.id)',
    createdAt: Date.now() - 86400000 * 88,
  },
  {
    id: 'm3',
    name: 'avg_order_value',
    description: 'Average value of an individual order',
    synonyms: ['aov', 'average order', 'mean order value'],
    status: 'Approved',
    dataType: 'currency',
    sourceDataset: 'Sales CSV',
    formula: 'SUM(orders.total_amount) / COUNT(orders.id)',
    createdAt: Date.now() - 86400000 * 85,
  },
  {
    id: 'm4',
    name: 'revenue_by_region',
    description: 'Revenue grouped by geographic sales region',
    synonyms: ['regional revenue', 'revenue by geography', 'sales by region'],
    status: 'Approved',
    dataType: 'currency',
    sourceDataset: 'Sales CSV',
    formula: 'SUM(orders.total_amount) GROUP BY regions.name',
    createdAt: Date.now() - 86400000 * 70,
  },
  {
    id: 'm5',
    name: 'orders_over_time',
    description: 'Order count trend over time periods',
    synonyms: ['order trend', 'orders timeline', 'order velocity'],
    status: 'Approved',
    dataType: 'number',
    sourceDataset: 'Sales CSV',
    formula: 'COUNT(orders.id) GROUP BY date_trunc(week, orders.created_at)',
    createdAt: Date.now() - 86400000 * 65,
  },
  {
    id: 'm6',
    name: 'employee_count',
    description: 'Total number of active employees',
    synonyms: ['headcount', 'staff count', 'workforce size'],
    status: 'Approved',
    dataType: 'number',
    sourceDataset: 'Employees',
    formula: 'COUNT(employees.id) WHERE employees.status = active',
    createdAt: Date.now() - 86400000 * 50,
  },
  {
    id: 'm7',
    name: 'customer_churn_rate',
    description: 'Percentage of customers lost in a period',
    synonyms: ['churn', 'attrition rate', 'customer loss rate'],
    status: 'Pending',
    dataType: 'percent',
    sourceDataset: 'Sales CSV',
    createdAt: Date.now() - 86400000 * 5,
  },
  {
    id: 'm8',
    name: 'net_revenue',
    description: 'Revenue after refunds and cancellations',
    synonyms: ['net sales', 'revenue after returns'],
    status: 'Pending',
    dataType: 'currency',
    sourceDataset: 'Sales CSV',
    createdAt: Date.now() - 86400000 * 3,
  },
];

export const datasets: Dataset[] = [
  {
    id: 'd1',
    name: 'Sales CSV',
    description: 'All sales transactions including order amount, region, and date',
    columns: 12,
    rows: 18430,
    piiMasked: true,
    status: 'Active',
    lastUpdated: Date.now() - 3600000 * 6,
    tags: ['sales', 'revenue', 'orders'],
  },
  {
    id: 'd2',
    name: 'Employees',
    description: 'Employee directory with department and status',
    columns: 8,
    rows: 423,
    piiMasked: true,
    status: 'Active',
    lastUpdated: Date.now() - 3600000 * 24,
    tags: ['hr', 'headcount'],
  },
  {
    id: 'd3',
    name: 'Customer Profiles',
    description: 'Customer accounts with demographics and lifecycle stage',
    columns: 15,
    rows: 8912,
    piiMasked: true,
    status: 'Active',
    lastUpdated: Date.now() - 3600000 * 48,
    tags: ['customers', 'crm'],
  },
  {
    id: 'd4',
    name: 'Product Catalog',
    description: 'Product master data with pricing and categories',
    columns: 6,
    rows: 1240,
    piiMasked: false,
    status: 'Active',
    lastUpdated: Date.now() - 3600000 * 72,
    tags: ['products', 'catalog'],
  },
  {
    id: 'd5',
    name: 'Web Events',
    description: 'Clickstream events from website and app',
    columns: 9,
    rows: 2341000,
    piiMasked: true,
    status: 'Syncing',
    lastUpdated: Date.now() - 60000 * 5,
    tags: ['events', 'analytics'],
  },
];

export const auditEntries: AuditEntry[] = [
  {
    id: 'a1',
    time: Date.now() - 60000 * 12,
    tenant: 'Acme Analytics',
    question: 'What is total revenue?',
    planType: 'single_metric',
    confidence: 'high',
    flags: [],
    claimedTools: ['total_revenue'],
    observedTools: ['total_revenue'],
    hasMismatch: false,
    userId: 'u1',
  },
  {
    id: 'a2',
    time: Date.now() - 60000 * 35,
    tenant: 'Acme Analytics',
    question: 'Revenue by region',
    planType: 'multi_metric',
    confidence: 'high',
    flags: [],
    claimedTools: ['revenue_by_region'],
    observedTools: ['revenue_by_region'],
    hasMismatch: false,
    userId: 'u1',
  },
  {
    id: 'a3',
    time: Date.now() - 60000 * 90,
    tenant: 'Demo Tenant',
    question: 'Show me churn rate for Q3',
    planType: 'single_metric',
    confidence: 'medium',
    flags: [{ type: 'metric_pending', label: 'Metric pending approval', severity: 'warning' }],
    claimedTools: ['customer_churn_rate'],
    observedTools: ['customer_churn_rate', 'raw_customers_table'],
    hasMismatch: true,
    userId: 'u2',
  },
  {
    id: 'a4',
    time: Date.now() - 60000 * 150,
    tenant: 'Acme Analytics',
    question: 'Describe the sales data',
    planType: 'describe_data',
    confidence: 'high',
    flags: [],
    claimedTools: ['describe_data_tool'],
    observedTools: ['describe_data_tool'],
    hasMismatch: false,
    userId: 'u1',
  },
  {
    id: 'a5',
    time: Date.now() - 60000 * 240,
    tenant: 'Demo Tenant',
    question: 'What is our SQL for revenue?',
    planType: 'single_metric',
    confidence: 'low',
    flags: [{ type: 'unknown_metric', label: 'Requested SQL generation — blocked', severity: 'critical' }],
    claimedTools: [],
    observedTools: [],
    hasMismatch: false,
    userId: 'u2',
  },
  {
    id: 'a6',
    time: Date.now() - 60000 * 360,
    tenant: 'Acme Analytics',
    question: 'Trend of orders over time',
    planType: 'trend_tool',
    confidence: 'high',
    flags: [],
    claimedTools: ['orders_over_time'],
    observedTools: ['orders_over_time'],
    hasMismatch: false,
    userId: 'u1',
  },
];

export const apiKeys: ApiKey[] = [
  {
    id: 'k1',
    label: 'Production API',
    prefix: 'daana_live_',
    createdAt: Date.now() - 86400000 * 45,
    lastUsed: Date.now() - 3600000 * 2,
    status: 'Active',
  },
  {
    id: 'k2',
    label: 'Webhook Integration',
    prefix: 'daana_live_',
    createdAt: Date.now() - 86400000 * 20,
    lastUsed: Date.now() - 3600000 * 24,
    status: 'Active',
  },
  {
    id: 'k3',
    label: 'Legacy Key',
    prefix: 'daana_test_',
    createdAt: Date.now() - 86400000 * 100,
    lastUsed: null,
    status: 'Revoked',
  },
];

export const systemHealth: SystemHealthStatus[] = [
  {
    endpoint: '/health',
    status: 'OK',
    detail: 'All systems operational',
    phase: '5',
    isolation: true,
    invariantSnippet: 'LLM executes 0 SQL, 0 Python — only metric/tool dispatch',
  },
  {
    endpoint: '/ready',
    status: 'OK',
    detail: 'Ready to serve traffic',
    phase: '5',
    isolation: true,
    invariantSnippet: 'Model output verified against approved metric registry',
  },
];

export const historyEntries: HistoryEntry[] = auditEntries.map((a) => ({
  id: a.id,
  question: a.question,
  timestamp: a.time,
  confidence: a.confidence,
  planType: a.planType,
  flags: a.flags,
  tenant: a.tenant,
}));

const INVARIANT = 'The LLM never generates or executes SQL or Python. It only selects from human-approved metrics and fixed tools.';

interface CannedResponse {
  match: (q: string) => boolean;
  response: AskResponse;
}

const cannedResponses: CannedResponse[] = [
  {
    match: (q) => /total revenue/.test(q) || /^revenue$/.test(q.trim()),
    response: {
      status: 'completed',
      answer: 'Total revenue is $57,000 across all regions. This covers all 1,843 orders in the Sales CSV dataset from Jan 1 to Sep 14, 2026.',
      confidence: 'high',
      flags: [],
      lineage: [{ name: 'total_revenue', kind: 'metric' }],
      plan_type: 'single_metric',
      invariant: INVARIANT,
      keyNumbers: [
        { label: 'Total Revenue', value: '$57,000' },
        { label: 'Orders', value: '1,843' },
      ],
      steps: [
        { label: 'Planning', status: 'done' },
        { label: 'Policy check', status: 'done' },
        { label: 'Running tools', status: 'done' },
        { label: 'Verifying', status: 'done' },
        { label: 'Writing answer', status: 'done' },
      ],
    },
  },
  {
    match: (q) => /revenue.*region|region.*revenue/.test(q),
    response: {
      status: 'completed',
      answer: 'Revenue is distributed across four regions. North America leads with $24,800 (43.5%), followed by Europe at $16,200 (28.4%), APAC at $10,100 (17.7%), and Latin America at $5,900 (10.4%).',
      confidence: 'high',
      flags: [],
      lineage: [{ name: 'revenue_by_region', kind: 'metric' }],
      plan_type: 'multi_metric',
      invariant: INVARIANT,
      chart: {
        type: 'bar',
        title: 'Revenue by Region',
        data: [
          { label: 'North America', value: 24800 },
          { label: 'Europe', value: 16200 },
          { label: 'APAC', value: 10100 },
          { label: 'Latin America', value: 5900 },
        ],
      },
      keyNumbers: [
        { label: 'Top Region', value: 'North America' },
        { label: 'Regions', value: '4' },
      ],
      steps: [
        { label: 'Planning', status: 'done' },
        { label: 'Policy check', status: 'done' },
        { label: 'Running tools', status: 'done' },
        { label: 'Verifying', status: 'done' },
        { label: 'Writing answer', status: 'done' },
      ],
    },
  },
  {
    match: (q) => /trend.*order|order.*time|orders.*over/.test(q),
    response: {
      status: 'completed',
      answer: 'Orders have been trending upward over the past 6 months. Weekly order count rose from 210 in March to 412 in September — a 96% increase. The steepest growth occurred in July (+18% week-over-week).',
      confidence: 'high',
      flags: [],
      lineage: [{ name: 'orders_over_time', kind: 'metric' }],
      plan_type: 'trend_tool',
      invariant: INVARIANT,
      chart: {
        type: 'line',
        title: 'Weekly Orders Trend',
        data: [
          { label: 'Mar', value: 210 },
          { label: 'Apr', value: 245 },
          { label: 'May', value: 280 },
          { label: 'Jun', value: 320 },
          { label: 'Jul', value: 378 },
          { label: 'Aug', value: 395 },
          { label: 'Sep', value: 412 },
        ],
      },
      keyNumbers: [
        { label: 'Latest Week', value: '412 orders' },
        { label: 'Trend', value: '+96% vs Mar' },
      ],
      steps: [
        { label: 'Planning', status: 'done' },
        { label: 'Policy check', status: 'done' },
        { label: 'Running tools', status: 'done' },
        { label: 'Verifying', status: 'done' },
        { label: 'Writing answer', status: 'done' },
      ],
    },
  },
  {
    match: (q) => /describe.*data|data.*describe|what.*data/.test(q),
    response: {
      status: 'completed',
      answer: 'The Sales CSV dataset contains 18,430 rows across 12 columns. Key columns include order_id, customer_id, total_amount, region, product_id, and created_at. PII columns (customer_name, email) are masked. The Employees dataset has 423 rows across 8 columns with department and status fields.',
      confidence: 'medium',
      flags: [],
      lineage: [
        { name: 'describe_data_tool', kind: 'tool' },
        { name: 'Sales CSV', kind: 'dataset' },
        { name: 'Employees', kind: 'dataset' },
      ],
      plan_type: 'describe_data',
      invariant: INVARIANT,
      caveat: 'Dataset descriptions are based on registered metadata. Column-level details may not reflect recent schema changes.',
      keyNumbers: [
        { label: 'Datasets', value: '2' },
        { label: 'Total Rows', value: '18,853' },
      ],
      steps: [
        { label: 'Planning', status: 'done' },
        { label: 'Policy check', status: 'done' },
        { label: 'Running tools', status: 'done' },
        { label: 'Verifying', status: 'done' },
        { label: 'Writing answer', status: 'done' },
      ],
    },
  },
  {
    match: (q) => /churn|sensitive|export.*data|show.*sql|write.*sql|run.*query/.test(q),
    response: {
      status: 'awaiting_confirmation',
      answer: '',
      confidence: 'medium',
      flags: [{ type: 'pii_risk', label: 'PII access requested', severity: 'warning' }],
      lineage: [{ name: 'customer_churn_rate', kind: 'metric' }],
      plan_type: 'confirmation_required',
      invariant: INVARIANT,
      planSummary: 'This request accesses customer_churn_rate (currently pending approval) and touches PII-masked columns in Customer Profiles. The model will only compute the approved aggregate — no raw customer records will be returned.',
      steps: [
        { label: 'Planning', status: 'done' },
        { label: 'Policy check', status: 'active' },
        { label: 'Running tools', status: 'pending' },
        { label: 'Verifying', status: 'pending' },
        { label: 'Writing answer', status: 'pending' },
      ],
    },
  },
];

function defaultResponse(question: string): AskResponse {
  return {
    status: 'completed',
    answer: `Based on approved metrics, here's what I found for "${question}": The Sales CSV dataset has 18,430 records. Total revenue stands at $57,000 across 1,843 orders, yielding an average order value of $30.93. Revenue is split across 4 regions with North America leading at $24,800.`,
    confidence: 'medium',
    flags: [{ type: 'quota_warning', label: 'Approaching daily query quota', severity: 'warning' }],
    lineage: [
      { name: 'total_revenue', kind: 'metric' },
      { name: 'order_count', kind: 'metric' },
    ],
    plan_type: 'stats_tool',
    invariant: INVARIANT,
    caveat: 'This response synthesized multiple metrics. Verify the specific metric you need for higher confidence.',
    keyNumbers: [
      { label: 'Total Revenue', value: '$57,000' },
      { label: 'Avg Order Value', value: '$30.93' },
    ],
    steps: [
      { label: 'Planning', status: 'done' },
      { label: 'Policy check', status: 'done' },
      { label: 'Running tools', status: 'done' },
      { label: 'Verifying', status: 'done' },
      { label: 'Writing answer', status: 'done' },
    ],
  };
}

function loadingSteps() {
  return [
    { label: 'Planning', status: 'active' },
    { label: 'Policy check', status: 'pending' },
    { label: 'Running tools', status: 'pending' },
    { label: 'Verifying', status: 'pending' },
    { label: 'Writing answer', status: 'pending' },
  ];
}

export async function mockAsk(question: string): Promise<AskResponse> {
  const lowerQ = question.toLowerCase();
  const canned = cannedResponses.find((c) => c.match(lowerQ));

  await new Promise((r) => setTimeout(r, 1200));

  if (canned) return canned.response;
  return defaultResponse(question);
}

export async function mockAskWithStepper(
  question: string,
  onStep: (steps: { label: string; status: 'done' | 'active' | 'pending' }[]) => void
): Promise<AskResponse> {
  const lowerQ = question.toLowerCase();
  const canned = cannedResponses.find((c) => c.match(lowerQ));

  const stepLabels = ['Planning', 'Policy check', 'Running tools', 'Verifying', 'Writing answer'];

  for (let i = 0; i < stepLabels.length; i++) {
    const steps = stepLabels.map((label, idx) => ({
      label,
      status: idx < i ? ('done' as const) : idx === i ? ('active' as const) : ('pending' as const),
    }));
    onStep(steps);
    await new Promise((r) => setTimeout(r, 350));
  }

  if (canned) return canned.response;
  return defaultResponse(question);
}

export { loadingSteps, INVARIANT, API_BASE };
