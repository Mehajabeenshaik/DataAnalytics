"""Deterministic LLM stub for offline trust evaluation / CI.

The MockTrustProvider implements the LLMProvider interface (generate,
generate_stream, provider_name) with simple keyword rules so the full
agent_phase2.ask() loop can run without GPU, API keys, or a network
connection.

It also captures every prompt sent to it (including system_prompt) so the
eval runner can verify that NO unmasked PII ever reaches the LLM-facing
payload — a key B2B trust property.
"""
from __future__ import annotations

import json
import re

from llm_provider import LLMProvider


def _extract_question(prompt: str) -> str:
    """Extract the user's question from the planner prompt.

    The planner prompt is built as:
        Schema: ...
        Allowed filter columns: ...
        Available metrics: [...]
        Available statistical tools: [...]
        Question: <the actual question>

    We match keywords against ONLY the question text, not the full prompt
    (which contains the metric catalog and could cause false matches).
    """
    idx = prompt.rfind("Question:")
    if idx == -1:
        return prompt
    return prompt[idx + len("Question:"):].strip()


def _extract_metric_catalog(prompt: str) -> set[str]:
    """Extract the metric names from the 'Available metrics:' JSON block.

    The planner prompt lists the approved metrics as JSON. We parse the
    names so the mock provider ONLY picks targets that exist in the real
    catalog — mimicking what a governed LLM planner must do.
    """
    names: set[str] = set()
    idx = prompt.find("Available metrics:")
    if idx == -1:
        return names
    start = prompt.find("[", idx)
    if start == -1:
        return names
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(prompt)):
        ch = prompt[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                raw = prompt[start:i + 1]
                try:
                    data = json.loads(raw)
                    for entry in data:
                        if isinstance(entry, dict) and entry.get("name"):
                            names.add(entry["name"])
                except Exception:
                    pass
                return names
    return names


# ── Synthesizer helpers: render results, not raw prompt text ──────────────

def _fmt_num(value) -> str:
    """Format a result number without leaking structural tokens or currency
    guesses: ints get thousands separators, floats get 2 decimals."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    try:
        fvalue = float(value)
    except (TypeError, ValueError):
        return str(value)
    if fvalue.is_integer():
        return f"{fvalue:,.0f}"
    return f"{fvalue:,.2f}"


def _result_label(entry: dict) -> str:
    """Human-readable label for a result entry, derived from its args.

    Tool names and arg keys are internal identifiers, so they are rendered as
    prose ('count of sales where category = Electronics') rather than leaking
    as-is or — worse — leaking the entry's structural step_id.
    """
    target = entry.get("target") or "result"
    args = entry.get("args") or {}
    if target == "categorical_filtered_agg":
        return (
            f"{args.get('agg', 'count')} of {args.get('value_col', 'rows')} "
            f"where {args.get('filter_col')} = {args.get('filter_value')}"
        )
    if target == "percentage_of_total":
        return (
            f"share of {args.get('value_col')} from "
            f"{args.get('filter_col')} = {args.get('filter_value')}"
        )
    return str(target).replace("_", " ")


def _render_result(entry: dict) -> str | None:
    """Render one serialized result entry as a short clause (or None)."""
    if entry.get("error"):
        return None
    value = entry.get("result")
    label = _result_label(entry)
    if isinstance(value, dict):
        items = [f"{k}: {_fmt_num(v)}" for k, v in list(value.items())[:4]]
        return f"{label} — " + "; ".join(items) if items else None
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            row = value[0]
            items = [f"{k}: {_fmt_num(v)}" for k, v in list(row.items())[:4]]
            return f"{label} (first row) — " + "; ".join(items) if items else None
        items = [_fmt_num(v) for v in value[:4]]
        return f"{label}: " + ", ".join(items) if items else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{label}: {_fmt_num(value)}"
    return None


class MockTrustProvider(LLMProvider):
    """Deterministic keyword-based LLM stub.

    Attributes:
        captured_prompts: list of (system_prompt, prompt) tuples sent to
            generate()/generate_stream(). Used for PII leak checks.
    """

    def __init__(self, track_prompts: bool = True):
        self.captured_prompts: list[tuple[str, str]] = []
        self.track_prompts = track_prompts

    def provider_name(self) -> str:
        return "mock/trust"

    def _capture(self, prompt: str, system_prompt: str = "") -> None:
        if self.track_prompts:
            self.captured_prompts.append((system_prompt or "", prompt))

    def _all_prompt_text(self) -> str:
        """Concatenate all captured prompt+system text for PII scanning."""
        return "\n".join(sp + "\n" + p for sp, p in self.captured_prompts)

    # ── Synthesizer helper: include numbers from the results ──────────────

    def _synthesize(self, prompt: str) -> str:
        """Build a synthesizer JSON response from the serialized results.

        The Results block is parsed as JSON and only each entry's `result`
        value is rendered — never structural fields (step_id, action) and
        never a dev-only marker — so the answer text reads like a real
        synthesizer answer. Numbers are still included so the golden
        `must_include_numbers` expectations pass.
        """
        clauses: list[str] = []
        m = re.search(r"Results:\n(\[.*)$", prompt, re.DOTALL)
        if m:
            try:
                entries = json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError):
                entries = []
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        clause = _render_result(entry)
                        if clause:
                            clauses.append(clause)

        if clauses:
            answer = "Based on the data: " + "; ".join(clauses) + "."
        else:
            answer = "No numeric result was produced by the tools."

        return json.dumps({
            "answer": answer,
            "confidence": "high",
            "caveats": [],
            "lineage": {"metrics_or_tools_used": [], "filters_applied": {}, "notes": "mock"},
        })

    # ── LLMProvider interface ─────────────────────────────────────────────

    def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> str:
        self._capture(prompt, system_prompt)
        sys_l = (system_prompt or "").lower()

        # Synthesizer path — include numbers from the results.
        if "senior data analyst" in sys_l:
            return self._synthesize(prompt)

        # Propose-metric path (planner asked for a new metric)
        if "proposing a new governed metric" in sys_l:
            return json.dumps({"can_propose": False, "reason": "mock provider declines propose"})

        # Planner path — match against the question only + real catalog names.
        q = _extract_question(prompt).lower()
        catalog_names = _extract_metric_catalog(prompt)

        def pick_target(name: str) -> str:
            """Return the real catalog metric matching a preferred name, or
            fall back to any 'total_*' metric (deterministic choice)."""
            if name in catalog_names:
                return name
            # Fall back to whatever total/sum metric exists.
            totals = sorted(n for n in catalog_names if n.startswith("total_"))
            if totals:
                return totals[0]
            sorted_names = sorted(catalog_names)
            if sorted_names:
                return sorted_names[0]
            return name  # let the agent's validation reject it

        # 1. Adversarial / out-of-scope / injection attempts
        if any(x in q for x in (
            "weather", "ignore all previous", "ignore previous", "dump all",
            "system prompt", "reveal your", "execute arbitrary sql",
            "capital of france", "tell me a joke", "internal instructions",
        )):
            return json.dumps({
                "can_answer": False,
                "reason": "out of scope or unsafe",
                "plan_type": "no_match",
                "steps": [],
            })

        # 2. Invented metric (should NEVER become a plan — validate step)
        if "total_revenue_evil" in q or "does not exist" in q:
            # The validation layer MUST reject this — we return it deliberately
            # to prove the governed planner rejects unknown metrics.
            return json.dumps({
                "can_answer": True,
                "reason": "pretending metric exists",
                "plan_type": "single_metric",
                "steps": [{
                    "step_id": 1,
                    "action": "run_metric",
                    "target": "total_revenue_evil",
                    "filters": {},
                    "args": {},
                }],
            })

        # 3. Simple total revenue / sales metric
        if "total revenue" in q or "total sales" in q or "average revenue" in q:
            preferred = "avg_" if ("average" in q or "avg" in q) else "total_"
            totals = sorted(n for n in catalog_names if n.startswith(preferred))
            target = totals[0] if totals else pick_target("")
            return json.dumps({
                "can_answer": True,
                "reason": "metric match",
                "plan_type": "single_metric",
                "steps": [{
                    "step_id": 1,
                    "action": "run_metric",
                    "target": target,
                    "filters": {},
                    "args": {},
                }],
            })

        # 4. Breakdown by region/category
        if "by region" in q or "by category" in q or "break down" in q \
                or "breakdown" in q or "per region" in q or "by department" in q:
            preferred = "sales_by_category" if ("category" in q or "categories" in q) else "sales_by_region"
            breakdowns = sorted(
                n for n in catalog_names
                if "by_" in n and ("region" in n or "category" in n or "department" in n or "sales" in n)
            )
            target = preferred if preferred in catalog_names else (breakdowns[0] if breakdowns else "")
            if not target:
                target = pick_target("")
            return json.dumps({
                "can_answer": True,
                "reason": "breakdown match",
                "plan_type": "single_metric",
                "steps": [{
                    "step_id": 1,
                    "action": "run_metric",
                    "target": target,
                    "filters": {},
                    "args": {},
                }],
            })

        # 5. Describe / summary / stats
        if any(x in q for x in (
            "describe", "summary", "summarize", "summarise",
            "statistics", "statistical", "overview",
        )):
            return json.dumps({
                "can_answer": True,
                "reason": "stats tool",
                "plan_type": "stats_tool",
                "steps": [{
                    "step_id": 1,
                    "action": "run_stats",
                    "target": "describe",
                    "filters": {},
                    "args": {},
                }],
            })

        # 6. Row count / order count
        if any(x in q for x in (
            "how many orders", "count of orders", "number of orders",
            "how many rows", "row count", "number of records", "dataset size",
        )):
            target = "row_count" if "row_count" in catalog_names else pick_target("")
            return json.dumps({
                "can_answer": True,
                "reason": "count metric",
                "plan_type": "single_metric",
                "steps": [{
                    "step_id": 1,
                    "action": "run_metric",
                    "target": target,
                    "filters": {},
                    "args": {},
                }],
            })

        # 7. Correlation
        if "correlation" in q:
            return json.dumps({
                "can_answer": True,
                "reason": "correlation tool",
                "plan_type": "stats_tool",
                "steps": [{
                    "step_id": 1,
                    "action": "run_stats",
                    "target": "correlation",
                    "filters": {},
                    "args": {},
                }],
            })

        # 8. Trend over time
        if "trend" in q or "over time" in q:
            return json.dumps({
                "can_answer": True,
                "reason": "trend tool",
                "plan_type": "stats_tool",
                "steps": [{
                    "step_id": 1,
                    "action": "run_stats",
                    "target": "trend",
                    "filters": {},
                    "args": {},
                }],
            })

        # 8.5 Nonexistent column reference (e.g. "product" not in schema)
        if "product" in q or "customer name" in q:
            return json.dumps({
                "can_answer": False,
                "reason": "No 'product' column exists. Available categorical columns: category, region, status.",
                "plan_type": "no_match",
                "steps": [],
            })

        # 9. PII-extraction attempts: emails/phones/names/addresses
        if any(x in q for x in (
            "email", "emails", "phone", "phones", "phone number",
            "phone numbers", "full names", "full name", "addresses",
            "home address", "names of employees",
        )):
            # Route to no_match so the answer contains no PII and the eval
            # confirms the agent declines rather than extracting PII.
            return json.dumps({
                "can_answer": False,
                "reason": "PII extraction is not a supported metric",
                "plan_type": "no_match",
                "steps": [],
            })

        # 10. Default: no reliable metric
        return json.dumps({
            "can_answer": False,
            "reason": "no reliable metric",
            "plan_type": "no_match",
            "steps": [],
        })

    def generate_stream(
        self, prompt: str, system_prompt: str = "", temperature: float = 0.1
    ):
        """Yield generate() output as a single chunk (default fallback)."""
        self._capture(prompt, system_prompt)
        yield self.generate(prompt, system_prompt=system_prompt, temperature=temperature)