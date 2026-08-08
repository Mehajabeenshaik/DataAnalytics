"""
Widget API router — endpoints for the embeddable chat bot.

All endpoints authenticate via X-API-Key header (tenant API key),
NOT JWT. This is intentional: the widget sits on customer websites
where end users don't log in — the API key identifies the company.
"""

from __future__ import annotations

import json
import uuid
import traceback
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse

from pydantic import BaseModel

from tenant import validate_api_key, Tenant
from session_manager import SessionManager
from data_source import DataSource
from llm_provider import get_provider
import agent_phase2
import stats_tools

widget_router = APIRouter(tags=["widget"])

# ── Shared state ──────────────────────────────────────────────────────────
_session_mgr = SessionManager()

# Maps session_id -> {"ds": DataSource, "tenant_key": str, "filename": str}
_widget_sessions: dict[str, dict] = {}

# Path to the widget JS file
_WIDGET_DIR = Path(__file__).resolve().parent / "widget"


# ── Auth dependency ───────────────────────────────────────────────────────

async def require_tenant(x_api_key: str = Header(...)) -> Tenant:
    """Validate X-API-Key header and return the Tenant."""
    tenant = validate_api_key(x_api_key)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    return tenant


# ── Request / Response models ─────────────────────────────────────────────

class SessionResponse(BaseModel):
    session_id: str
    message: str


class UploadResponse(BaseModel):
    session_id: str
    filename: str
    rows: int
    columns: int
    summary: str
    sections: list[dict] = []


class AskRequest(BaseModel):
    session_id: str
    question: str


class AskResponse(BaseModel):
    answer: str
    confidence: str = "n/a"
    caveats: list[str] = []
    lineage: dict = {}


class SessionInfoResponse(BaseModel):
    session_id: str
    filename: str
    rows: int
    columns: int
    schema_card: str


class TenantSettingsResponse(BaseModel):
    company_name: str
    settings: dict


# ── Serve widget.js ──────────────────────────────────────────────────────

@widget_router.get("/widget/widget.js")
async def serve_widget_js():
    """Serve the embeddable widget script. No auth required."""
    js_path = _WIDGET_DIR / "widget.js"
    if not js_path.exists():
        raise HTTPException(status_code=404, detail="Widget not built yet")
    return FileResponse(
        str(js_path),
        media_type="application/javascript",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
        },
    )


# ── Tenant settings (for widget theming) ─────────────────────────────────

@widget_router.get("/api/v1/tenant", response_model=TenantSettingsResponse)
async def get_tenant_settings(tenant: Tenant = Depends(require_tenant)):
    """Return tenant settings so the widget can apply theming."""
    return TenantSettingsResponse(
        company_name=tenant.company_name,
        settings=tenant.settings,
    )


# ── Create session ───────────────────────────────────────────────────────

@widget_router.post("/api/v1/session", response_model=SessionResponse)
async def create_session(tenant: Tenant = Depends(require_tenant)):
    """Create a new analysis session for this tenant."""
    session_id = str(uuid.uuid4())
    _session_mgr.create_session(session_id)
    _widget_sessions[session_id] = {
        "ds": None,
        "tenant_key": tenant.api_key,
        "filename": None,
    }
    return SessionResponse(
        session_id=session_id,
        message="Session created. Upload a file to start analysis.",
    )


# ── Upload + baseline analysis ───────────────────────────────────────────

def _build_baseline_analysis(ds: DataSource) -> tuple[str, list[dict]]:
    """Run deterministic stats and build a structured response.

    No LLM call — this is fast and reliable.
    Returns (summary_text, sections_list).
    """
    profile = ds.profile
    sections: list[dict] = []

    # 1. Overview
    summary = (
        f"Loaded **{profile.n_rows:,}** rows × **{profile.n_cols}** columns. "
        f"Here's what I found:"
    )

    # 2. Summary statistics (describe)
    try:
        desc_df = stats_tools.describe(ds)
        desc_records = desc_df.reset_index().to_dict(orient="records")
        # Clean up for JSON
        for row in desc_records:
            for k, v in row.items():
                if isinstance(v, float) and pd.isna(v):
                    row[k] = None
                elif isinstance(v, float):
                    row[k] = round(v, 2)
        sections.append({
            "title": "Summary Statistics",
            "type": "table",
            "data": desc_records,
        })
    except Exception:
        pass

    # 3. Missing values
    try:
        miss_df = stats_tools.missingness(ds)
        # Only show columns with > 0 nulls
        miss_df = miss_df[miss_df["null_count"] > 0]
        if not miss_df.empty:
            sections.append({
                "title": "Missing Values",
                "type": "table",
                "data": miss_df.to_dict(orient="records"),
            })
    except Exception:
        pass

    # 4. Top value counts for first categorical column (for a chart)
    try:
        if profile and profile.columns:
            cat_cols = [c for c in profile.columns if c.is_categorical]
            if cat_cols:
                col = cat_cols[0]
                vc_df = stats_tools.value_counts(ds, col.name, top_n=8)
                sections.append({
                    "title": f"Distribution: {col.name}",
                    "type": "bar_chart",
                    "data": {
                        "labels": vc_df[col.name].tolist(),
                        "values": vc_df["count"].tolist(),
                        "column": col.name,
                    },
                })
    except Exception:
        pass

    # 5. Trend chart for first numeric + temporal pair
    try:
        if profile and profile.columns:
            num_cols = [c for c in profile.columns if c.is_numeric]
            temp_cols = [c for c in profile.columns if c.is_temporal]
            if num_cols and temp_cols:
                trend_df = stats_tools.trend(ds, temp_cols[0].name, num_cols[0].name, freq="M")
                sections.append({
                    "title": f"Trend: {num_cols[0].name} over {temp_cols[0].name}",
                    "type": "line_chart",
                    "data": {
                        "labels": trend_df["period"].astype(str).tolist(),
                        "values": [round(v, 2) for v in trend_df["value"].tolist()],
                        "x_label": temp_cols[0].name,
                        "y_label": num_cols[0].name,
                    },
                })
    except Exception:
        pass

    return summary, sections


@widget_router.post("/api/v1/upload", response_model=UploadResponse)

async def upload_file(
    file: UploadFile = File(...),
    session_id: str | None = Form(None),
    tenant: Tenant = Depends(require_tenant),
):

    """Upload a data file and get baseline analysis.

    If session_id is provided, reuses that session.
    Otherwise creates a new one.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    suffix = Path(file.filename).suffix.lower()
    allowed = {".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet", ".pq"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: {', '.join(sorted(allowed))}",
        )

    # Max file size check (default 50MB, configurable per tenant)
    max_mb = tenant.settings.get("max_file_size_mb", 50)
    content = await file.read()
    if len(content) > max_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum: {max_mb}MB",
        )

    # Create or reuse session
    if not session_id:
        session_id = str(uuid.uuid4())
        _session_mgr.create_session(session_id)

    try:
        # Save to temp file
        session_info = _session_mgr.get_session(session_id)
        temp_dir = session_info["temp_dir"] if session_info else tempfile.mkdtemp()

        file_path = Path(temp_dir) / file.filename
        with open(file_path, "wb") as f:
            f.write(content)

        # Load into DataSource
        ds = DataSource(name=file.filename)
        ds.load_file(str(file_path))

        _widget_sessions[session_id] = {
            "ds": ds,
            "tenant_key": tenant.api_key,
            "filename": file.filename,
        }
        _session_mgr.touch(session_id)

        # Run baseline analysis (deterministic, no LLM)
        summary, sections = _build_baseline_analysis(ds)

        return UploadResponse(
            session_id=session_id,
            filename=file.filename,
            rows=ds.profile.n_rows if ds.profile else 0,
            columns=ds.profile.n_cols if ds.profile else 0,
            summary=summary,
            sections=sections,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


# ── Follow-up Q&A ───────────────────────────────────────────────────────

def _resolve_widget_session(req: AskRequest, tenant: Tenant) -> dict:
    """Validate session ownership and return the session record.

    Shared by both /api/v1/ask and /api/v1/ask/stream so the session lookup,
    tenant-isolation check, and session touch are NOT duplicated between the
    blocking and streaming endpoints. Raises HTTPException on failure.
    """
    session = _widget_sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Tenant isolation: verify this session belongs to this API key
    if session["tenant_key"] != tenant.api_key:
        raise HTTPException(status_code=403, detail="Session does not belong to this API key")

    if session["ds"] is None:
        raise HTTPException(status_code=400, detail="No data uploaded in this session yet")

    _session_mgr.touch(req.session_id)
    return session


@widget_router.post("/api/v1/ask", response_model=AskResponse)
async def ask_question(
    req: AskRequest,
    tenant: Tenant = Depends(require_tenant),
):
    """Ask a natural-language follow-up question about the uploaded data."""
    session = _resolve_widget_session(req, tenant)

    try:
        provider = get_provider()
        ds = session["ds"]
        result = agent_phase2.ask(req.question, ds, provider)

        # Serialize any pandas objects in results
        return AskResponse(
            answer=result.get("answer", ""),
            confidence=result.get("confidence", "n/a"),
            caveats=result.get("caveats", []),
            lineage=result.get("lineage", {}),
        )
    except ConnectionError as e:
        raise HTTPException(
            status_code=503,
            detail=f"LLM service unavailable: {str(e)}",
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@widget_router.post("/api/v1/ask/stream")
async def ask_question_stream(
    req: AskRequest,
    tenant: Tenant = Depends(require_tenant),
):
    """Ask a follow-up question, streaming the answer as SSE.

    Reuses the exact same auth/session validation as /api/v1/ask (via
    _resolve_widget_session + require_tenant). Emits SSE events:
      data: {"type": "chunk", "text": "..."}      — synthesizer token chunks
      data: {"type": "final", "data": {...}}       — full structured response

    Note on auth: because EventSource does NOT support custom headers,
    widget.js uses fetch() + a ReadableStream reader against this endpoint
    with the X-API-Key header, rather than the EventSource API directly.
    """
    session = _resolve_widget_session(req, tenant)

    async def event_generator():
        try:
            provider = get_provider()
            ds = session["ds"]
            for event in agent_phase2.ask_stream(req.question, ds, provider):
                if isinstance(event, str):
                    yield _sse({"type": "chunk", "text": event})
                else:
                    # Final structured event — serialize safely (no pandas)
                    yield _sse({
                        "type": "final",
                        "data": {
                            "answer": event.get("answer", ""),
                            "confidence": event.get("confidence", "n/a"),
                            "caveats": event.get("caveats", []),
                            "lineage": event.get("lineage", {}),
                        },
                    })
        except ConnectionError as e:
            yield _sse({"type": "error", "message": f"LLM service unavailable: {e}"})
        except Exception:
            traceback.print_exc()
            yield _sse({"type": "error", "message": "Query failed"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(payload: dict) -> str:
    """Serialize a dict as an SSE 'data:' event."""
    return f"data: {json.dumps(payload, default=str)}\n\n"


# ── Session info ─────────────────────────────────────────────────────────

@widget_router.get("/api/v1/session/{session_id}", response_model=SessionInfoResponse)
async def get_session_info(
    session_id: str,
    tenant: Tenant = Depends(require_tenant),
):
    """Get info about an active session."""
    session = _widget_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session["tenant_key"] != tenant.api_key:
        raise HTTPException(status_code=403, detail="Session does not belong to this API key")

    ds = session["ds"]
    if ds is None:
        raise HTTPException(status_code=400, detail="No data uploaded in this session yet")

    return SessionInfoResponse(
        session_id=session_id,
        filename=session["filename"] or "",
        rows=ds.profile.n_rows if ds.profile else 0,
        columns=ds.profile.n_cols if ds.profile else 0,
        schema_card=ds.get_schema_card(),
    )
