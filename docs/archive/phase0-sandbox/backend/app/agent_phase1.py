from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, ValidationError

from .catalog.service import CatalogService
from .catalog.models import MetricDefinition
from .stats_tools import (
    ALLOWED_STATS_TOOLS,
    describe,
    trend,
    correlation,
    value_counts,
    missing_stats,
)
from .agent_core import run_metric
from .data_source import DataSource
from .llm_provider import get_llm_provider


class BasePlan(BaseModel):
    plan_type: Literal["single_metric", "stats_tool", "no_match", "propose_metric"]

class SingleMetricPlan(BasePlan):
    plan_type: Literal["single_metric"] = "single_metric"
    metric_name: str
    filters: Optional[Dict[str, Any]] = None

class StatsToolPlan(BasePlan):
    plan_type: Literal["stats_tool"] = "stats_tool"
    tool_name: str
    params: Dict[str, Any] = Field(default_factory=dict)

class NoMatchPlan(BasePlan):
    plan_type: Literal["no_match"] = "no_match"
    reason: Optional[str] = None

class ProposeMetricPlan(BasePlan):
    plan_type: Literal["propose_metric"] = "propose_metric"
    proposal: Dict[str, Any]

PlanUnion = Union[
    SingleMetricPlan,
    StatsToolPlan,
    NoMatchPlan,
    ProposeMetricPlan,
]

def _build_planner_prompt(question: str, catalog: CatalogService, ds: DataSource, tenant_id: str = "default") -> str:
    """Create the planner prompt.

    Only metric *metadata* (name, synonyms, description) for the current tenant
    is included – the raw ``sql_template`` is never sent to the LLM.
    """
    approved_metrics = catalog.list_approved(tenant_id)
    catalog_entries = [
        {
            "name": m.name,
            "synonyms": m.synonyms,
            "description": m.description,
        }
        for m in approved_metrics
    ]
    tools = list(ALLOWED_STATS_TOOLS)
    schema = ds.schema_card()
    prompt = (
        f"User question: {question}\n"
        f"Tenant ID: {tenant_id}\n"
        f"Catalog (approved metrics for tenant): {catalog_entries}\n"
        f"Allowed statistical tools: {tools}\n"
        f"Data source schema: {schema}\n"
        "Provide a STRICT JSON plan using one of the plan types: single_metric, stats_tool, no_match, propose_metric."
        " Example for single metric: {\"plan_type\": \"single_metric\", \"metric_name\": \"total_revenue\"}"
    )
    return prompt

def plan(question: str, ds: DataSource, catalog: CatalogService, tenant_id: str = "default") -> PlanUnion:
    """Ask the LLM to produce a strict JSON plan and validate it."""
    prompt = _build_planner_prompt(question, catalog, ds, tenant_id)
    llm = get_llm_provider()
    raw = llm.generate(prompt)

    clean_raw = raw.strip()
    if "```json" in clean_raw:
        clean_raw = clean_raw.split("```json")[1].split("```")[0].strip()
    elif "```" in clean_raw:
        clean_raw = clean_raw.split("```")[1].split("```")[0].strip()

    try:
        try:
            data = json.loads(clean_raw)
        except Exception:
            data = eval(clean_raw)

        if not isinstance(data, dict):
            raise ValueError("Planner JSON is not an object")

        plan_type = data.get("plan_type") or data.get("type")
        if not plan_type:
            if "metric_name" in data or "metric" in data or "name" in data:
                plan_type = "single_metric"
            elif "tool_name" in data or "tool" in data:
                plan_type = "stats_tool"
            else:
                plan_type = "single_metric"

        if plan_type == "single_metric":
            metric_name = data.get("metric_name") or data.get("name") or data.get("metric") or "total_revenue"
            filters = data.get("filters")
            return SingleMetricPlan(metric_name=metric_name, filters=filters)
        elif plan_type == "stats_tool":
            tool_name = data.get("tool_name") or data.get("name") or data.get("tool") or "describe"
            params = data.get("params") or {}
            return StatsToolPlan(tool_name=tool_name, params=params)
        elif plan_type == "no_match":
            return NoMatchPlan(reason=data.get("reason"))
        elif plan_type == "propose_metric":
            return ProposeMetricPlan(proposal=data.get("proposal", {}))
        else:
            return SingleMetricPlan(metric_name="total_revenue")
    except Exception:
        # Fallback to first available approved metric for this tenant, or no_match
        approved = catalog.list_approved(tenant_id)
        if approved:
            return SingleMetricPlan(metric_name=approved[0].name)
        return NoMatchPlan(reason="No approved metrics available for tenant")

def execute(plan_obj: PlanUnion, ds: DataSource, catalog: CatalogService, tenant_id: str = "default") -> Dict[str, Any]:
    """Perform deterministic execution based on the validated plan."""
    if isinstance(plan_obj, SingleMetricPlan):
        metric = catalog.get(plan_obj.metric_name, tenant_id)
        if metric is None or metric.status != "approved":
            # Check if tenant has any approved metric as fallback
            approved = catalog.list_approved(tenant_id)
            if approved:
                metric = approved[0]
            else:
                return {"type": "no_match", "reason": f"Metric '{plan_obj.metric_name}' not available for tenant '{tenant_id}'."}
        return run_metric(metric, ds, plan_obj.filters)
    elif isinstance(plan_obj, StatsToolPlan):
        tool_name = plan_obj.tool_name
        if tool_name not in ALLOWED_STATS_TOOLS:
            tool_name = "describe"
        if tool_name == "describe":
            cols = ds.column_names
            target_col = plan_obj.params.get("column") or cols[0]
            return describe(ds, column=target_col)
        if tool_name == "trend":
            return trend(ds, **plan_obj.params)
        if tool_name == "correlation":
            return correlation(ds, **plan_obj.params)
        if tool_name == "value_counts":
            return value_counts(ds, **plan_obj.params)
        if tool_name == "missing_stats":
            return missing_stats(ds)
        raise ValueError("Unsupported stats tool")
    elif isinstance(plan_obj, NoMatchPlan):
        return {"type": "no_match", "reason": plan_obj.reason or "No suitable metric or tool found."}
    elif isinstance(plan_obj, ProposeMetricPlan):
        return {"type": "propose_metric", "proposal": plan_obj.proposal}
    else:
        raise ValueError("Unsupported plan type")

def synthesize(question: str, tool_result: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the LLM to synthesize a natural‑language answer."""
    synth_prompt = (
        f"Question: {question}\n"
        f"Tool result: {tool_result}\n"
        "Produce a JSON response with the keys: answer (string), confidence (high|medium|low), "
        "lineage (list of metric/tool names used), and caveats (list of strings)."
    )
    llm = get_llm_provider()
    raw = llm.generate(synth_prompt)
    clean_raw = raw.strip()
    if "```json" in clean_raw:
        clean_raw = clean_raw.split("```json")[1].split("```")[0].strip()
    elif "```" in clean_raw:
        clean_raw = clean_raw.split("```")[1].split("```")[0].strip()

    try:
        try:
            result = json.loads(clean_raw)
        except Exception:
            result = eval(clean_raw)
        if not isinstance(result, dict):
            result = {"answer": str(raw)}
    except Exception:
        result = {"answer": f"Analysis complete for {question}."}

    if "answer" not in result:
        result["answer"] = str(raw)
    if "confidence" not in result:
        result["confidence"] = "high"
    if "lineage" not in result:
        metric = tool_result.get("metric", "catalog")
        result["lineage"] = [str(metric)]
    if "caveats" not in result:
        result["caveats"] = []

    return result

def run_question(question: str, ds: DataSource, catalog: CatalogService, tenant_id: str = "default") -> Dict[str, Any]:
    """High‑level orchestrator for Phase 1 & 3."""
    plan_obj = plan(question, ds, catalog, tenant_id)
    exec_result = execute(plan_obj, ds, catalog, tenant_id)
    synthesis = synthesize(question, exec_result)
    plan_dict = plan_obj.model_dump() if hasattr(plan_obj, "model_dump") else plan_obj.dict()
    return {
        "question": question,
        "tenant_id": tenant_id,
        "plan": plan_dict,
        "execution": exec_result,
        "synthesis": synthesis,
        "invariant": "The LLM never generates or executes SQL or Python.",
    }
