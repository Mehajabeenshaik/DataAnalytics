"""SSO infrastructure. Re-exports the sso package from backend.app.sso."""

from ...sso import get_sso_provider
from ...sso.base import SSOUser

__all__ = ["get_sso_provider", "SSOUser"]