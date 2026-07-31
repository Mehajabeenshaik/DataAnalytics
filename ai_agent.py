""" Core AI reasoning module. Zero Streamlit/app.py dependencies —
must be fully testable and runnable from a plain script.
"""

import json
import pandas as pd
from pydantic import BaseModel, ValidationError, field_validator

from data_layer import query_enriched
from pii_masker import PIIMasker
from metrics import METRICS, ALLOWED_FILTER_COLUMNS, get_metric_catalog_for_llm
from llm_provider import LLMProvider


# ── Step 1: metric selection (LLM call #1) ──────────────────────────────

class MetricSelection(BaseModel):
    metric_name: str | None = None
    filters: dict = {}
    no_match: bool = False

    @field_validator("metric_name")
    @classmethod
    def must_be_allowed(cls, v):
        if v is not None and v not in METRICS:
            # Never trust an LLM-invented metric name — force no_match instead.
            return None
        return v


def select_metric(question: str, provider: LLMProvider) -> MetricSelection:
    catalog = get_metric_catalog_for_llm()
    system_prompt = (
        "You are a metric router. Choose exactly ONE metric from the provided "
        "list that best answers the user's question, plus any relevant filters "
        f"from these allowed filter columns: {ALLOWED_FILTER_COLUMNS}. "
        "If nothing in the list genuinely answers the question, return "
        '{"no_match": true} instead of guessing. '
        "Respond ONLY with valid JSON: "
        '{"metric_name": "<name or null>", "filters": {"<col>": "<value>"}, "no_match": false}'
    )
    prompt = f"Available metrics:\n{json.dumps(catalog, indent=2)}\n\nQuestion: {question}"

    raw = provider.generate(prompt, system_prompt=system_prompt)

    try:
        data = json.loads(raw)
        selection = MetricSelection(**data)
    except (json.JSONDecodeError, ValidationError):
        # Malformed response = treat as no_match, never guess a fallback metric.
        return MetricSelection(no_match=True)

    if selection.metric_name is None and not selection.no_match:
        selection.no_match = True

    # Strip any filter keys outside the allowlist rather than trusting them.
    selection.filters = {
        k: v for k, v in selection.filters.items() if k in ALLOWED_FILTER_COLUMNS
    }
    return selection


# ── Step 2: deterministic query execution (NO LLM call) ─────────────────

def run_metric(metric_name: str, filters: dict) -> pd.Series | float | int:
    metric = METRICS[metric_name]  # KeyError is fine here — caller already validated
    combined_filters = {**metric["base_filters"], **filters}

    # query_enriched() calls resolve_filter() internally — we pass the filter
    # dict, never a raw SQL fragment, so the allowlist + parameterized
    # binding protections in data_layer.py are always enforced.
    df = query_enriched(filters=combined_filters)

    if metric["agg"] == "sum":
        result = df.groupby(metric["groupby"])[metric["column"]].sum() if metric["groupby"] \
            else df[metric["column"]].sum()
    elif metric["agg"] == "nunique":
        result = df[metric["column"]].nunique()
    elif metric["agg"] == "derived_aov":
        revenue = df["line_total"].sum()
        orders = df["order_id"].nunique()
        result = round(revenue / orders, 2) if orders else 0
    elif metric["agg"] == "derived_refund_rate":
        total_orders = df["order_id"].nunique()
        refunded = df[df["order_status"].isin(["returned", "cancelled"])]["order_id"].nunique()
        result = round(100 * refunded / total_orders, 2) if total_orders else 0
    else:
        raise ValueError(f"Unknown aggregation type for metric {metric_name}")

    return result


# ── Step 3: PII defense-in-depth (values are already masked at seed time) ─

def scrub_results(result) -> object:
    """
    Defensive scrub in case any freeform text ever ends up in a result.
    Customers are already masked at seed time (pii_masker.py), so this
    is a second layer, not the primary protection.
    """
    masker = PIIMasker()
    if isinstance(result, str):
        detections = masker.scan_text(result)
        if detections:
            return "[REDACTED - possible PII detected]"
        return result
    return result  # numbers/Series/dicts pass through untouched


# ── Step 4: explanation (LLM call #2) ────────────────────────────────────

class Explanation(BaseModel):
    answer: str
    metric_used: str
    confidence: str  # "high" | "low"
    caveat: str | None = None


def explain(question: str, metric_name: str, result, provider: LLMProvider) -> Explanation:
    safe_result = scrub_results(result)
    low_confidence = isinstance(safe_result, (int, float)) and False  # extend as needed
    is_small_series = hasattr(safe_result, "__len__") and len(safe_result) < 3

    system_prompt = (
        "Explain this business metric result in plain English for a "
        "non-technical business owner. Respond ONLY with valid JSON: "
        '{"answer": "...", "confidence": "high"|"low", "caveat": "..."|null}. '
        "Set confidence to 'low' and include a caveat if the result set is "
        "small, ambiguous, or the question implies causation the data alone "
        "can't fully support (e.g. correlation shown but not proven cause)."
    )
    prompt = f"Question: {question}\nMetric used: {metric_name}\nResult: {safe_result}"

    raw = provider.generate(prompt, system_prompt=system_prompt)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"answer": str(safe_result), "confidence": "low",
                "caveat": "Could not generate a full explanation; showing raw result."}

    if is_small_series and data.get("confidence") == "high":
        data["confidence"] = "low"
        data["caveat"] = (data.get("caveat") or "") + " Small result set — treat with caution."

    return Explanation(metric_used=metric_name, **data)


# ── Top-level entrypoint ─────────────────────────────────────────────────

def ask(question: str, provider: LLMProvider) -> dict:
    selection = select_metric(question, provider)

    if selection.no_match or not selection.metric_name:
        return {
            "answer": "I don't have a defined metric that answers this question yet.",
            "metric_used": None,
            "confidence": "n/a",
            "caveat": "No matching metric in the allowlist.",
        }

    result = run_metric(selection.metric_name, selection.filters)
    explanation = explain(question, selection.metric_name, result, provider)
    return explanation.model_dump()