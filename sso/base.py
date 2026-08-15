from __future__ import annotations
from pydantic import BaseModel

class SSOUser(BaseModel):
    email: str
    name: str = ""
    external_id: str = ""
    provider: str = "local"