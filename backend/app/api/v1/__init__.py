"""v1 API routers.

Phase 1 exposed ``oauth`` + ``accounts``. Phase 2 added ``rubric``
(classification rule CRUD). Phase 4 added ``jobs`` (read-only curated
match listing) + ``job-filters`` (predicate CRUD). Phase 5 adds
``unsubscribes`` (top-N recommendations + dismiss/confirm) and
``hygiene`` (summary stats card). Later phases register preferences,
digests, emails, admin.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.accounts import router as accounts_router
from app.api.v1.job_filters import router as job_filters_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.oauth import router as oauth_router
from app.api.v1.rubric import router as rubric_router
from app.api.v1.unsubscribes import hygiene_router, unsubscribes_router

api_router = APIRouter(prefix="/api/v1")
"""Top-level v1 router — include this one on the FastAPI app."""

api_router.include_router(oauth_router)
api_router.include_router(accounts_router)
api_router.include_router(rubric_router)
api_router.include_router(jobs_router)
api_router.include_router(job_filters_router)
api_router.include_router(unsubscribes_router)
api_router.include_router(hygiene_router)

__all__ = ["api_router"]
