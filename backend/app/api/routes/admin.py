"""Admin API routes. Re-exports the router from backend.app.admin_api."""

from ...admin_api import admin_router

__all__ = ["admin_router"]