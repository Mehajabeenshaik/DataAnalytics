"""
DataAnalytics FastAPI application entry point.

The FastAPI app object lives in backend/app/auth.py (kept there to preserve
all internal imports and behavior). This module re-exports it so the canonical
run command is:

    uvicorn backend.app.main:app --reload --port 8001
"""

from .auth import app

__all__ = ["app"]