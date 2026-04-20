"""v1 API routers.

Phase 1 exposes the `oauth` + `accounts` routers only. Later phases
register preferences, digests, emails, jobs, unsubscribes, admin.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.accounts import router as accounts_router
from app.api.v1.oauth import router as oauth_router

api_router = APIRouter(prefix="/api/v1")
"""Top-level v1 router — include this one on the FastAPI app."""

api_router.include_router(oauth_router)
api_router.include_router(accounts_router)

__all__ = ["api_router"]
