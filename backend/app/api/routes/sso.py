"""SSO API routes. Re-exports the router from backend.app.auth_sso_routes."""

from ...auth_sso_routes import sso_router

__all__ = ["sso_router"]