"""Seed the LOCAL dev database with demo data for clicking through the redesign.

NOT for production. Creates (or resets) a dedicated demo user + Gmail account and
writes enough data to exercise the redesigned pages end to end:

* a completed digest run + classified, unread emails (with summaries) across the
  must-read / good-to-read / ignore buckets — populates the two-pane home reader;
* unsubscribe suggestions with ``recent_subjects``, varied stats/tags, and a mix
  of one-click HTTPS / HTTP-only / ``mailto:`` targets — populates the unsubscribe
  page (and exercises the Track 5 execute outcomes when the flag is on).

Content is written through the application's own repos, so it is encrypted with
the same content CMK the API decrypts with (LocalStack KMS locally). The script
prints a signed ``briefed_session`` cookie so you can log in as the demo user
without the Google OAuth flow.

Usage (from the repo root, with .env's AWS_* exported so boto3 reaches LocalStack)::

    export $(grep -E '^AWS_' .env | xargs)
    PYTHONPATH=backend .venv/bin/python backend/scripts/seed_local_demo.py

Re-running fully resets the demo user (its emails/suggestions/runs cascade away).
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.api.session import SESSION_COOKIE_NAME, sign_cookie
from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.db.models import ConnectedAccount, DigestRun, Email, User
from app.db.session import get_sessionmaker
from app.services.classification.repository import ClassificationsRepo, ClassificationWrite
from app.services.summarization.repository import SummariesRepo, SummaryEmailWrite
from app.services.unsubscribe.repository import (
    UnsubscribeSuggestionsRepo,
    UnsubscribeSuggestionWrite,
)

DEMO_EMAIL = "demo@briefeddemo.com"
"""Dedicated demo identity — kept separate from any real connected account.

Uses a non-reserved domain because ``EmailRowOut.account_email`` is validated
as an ``EmailStr`` (reserved TLDs like ``.local`` / ``.example`` are rejected).
"""


@dataclass(frozen=True)
class _SeedEmail:
    """One demo email + its classification + optional summary."""

    gmail_id: str
    from_addr: str
    subject: str
    bucket: str
    decision_source: str
    needs_review: bool
    score: str
    reasons: tuple[str, ...]
    summary: str | None


_EMAILS: tuple[_SeedEmail, ...] = (
    _SeedEmail(
        gmail_id="demo-1",
        from_addr="Dana Cole <ceo@bigco.example>",
        subject="Q3 board deck — your section needs a final pass",
        bucket="must_read",
        decision_source="rule",
        needs_review=False,
        score="0.94",
        reasons=("Sender is on your VIP rules.", "Mentions a deadline this week."),
        summary=(
            "**TL;DR** Dana needs your revenue slides finalized before Thursday's"
            " board review.\n\n- Update the Q3 ARR chart\n- Confirm the churn figure"
            " with Finance\n- Send back by EOD Wednesday"
        ),
    ),
    _SeedEmail(
        gmail_id="demo-2",
        from_addr="British Airways <noreply@ba.example>",
        subject="Your flight BA242 is delayed",
        bucket="must_read",
        decision_source="hybrid",
        needs_review=True,
        score="0.61",
        reasons=("Time-sensitive travel update.", "Low confidence — double-check the new gate."),
        summary="**TL;DR** BA242 (JFK→LHR) now departs 21:40, gate B32. Re-check connections.",
    ),
    _SeedEmail(
        gmail_id="demo-3",
        from_addr="Product Hunt <news@producthunt.example>",
        subject="Today's top 5 launches",
        bucket="good_to_read",
        decision_source="model",
        needs_review=False,
        score="0.78",
        reasons=("Newsletter you open most weeks.",),
        summary="**TL;DR** An AI meeting-notes tool and a Postgres GUI top today's list.",
    ),
    _SeedEmail(
        gmail_id="demo-4",
        from_addr="Stripe <billing@stripe.example>",
        subject="Your invoice for May is ready",
        bucket="good_to_read",
        decision_source="rule",
        needs_review=False,
        score="0.82",
        reasons=("Billing from a service you use.",),
        summary=None,
    ),
    _SeedEmail(
        gmail_id="demo-5",
        from_addr="MegaDeals <deals@promo.example>",
        subject="🔥 50% OFF everything — today only!",
        bucket="ignore",
        decision_source="rule",
        needs_review=False,
        score="0.97",
        reasons=("High-volume promotional sender.", "You never open these."),
        summary=None,
    ),
)


@dataclass(frozen=True)
class _SeedSender:
    """One demo unsubscribe suggestion."""

    sender_email: str
    sender_domain: str
    frequency_30d: int
    engagement_score: str
    waste_rate: str
    confidence: str
    decision_source: str
    rationale: str
    http_urls: tuple[str, ...]
    mailto: str | None
    one_click: bool
    recent_subjects: tuple[str, ...]


_SENDERS: tuple[_SeedSender, ...] = (
    _SeedSender(
        sender_email="deals@promo.example",
        sender_domain="promo.example",
        frequency_30d=42,
        engagement_score="0.020",
        waste_rate="0.880",
        confidence="0.920",
        decision_source="rule",
        rationale="42 emails in 30 days, 2% opened, 88% wasted — all three criteria triggered.",
        # Reachable test endpoint (returns 200) so the execute one-click path
        # demos a real "unsubscribed" outcome, not a DNS failure.
        http_urls=("https://httpbin.org/status/200",),
        mailto=None,
        one_click=True,
        recent_subjects=(
            "50% OFF everything",
            "Flash sale ends tonight",
            "Last chance — 6 hrs left",
        ),
    ),
    _SeedSender(
        sender_email="newsletter@medium.example",
        sender_domain="medium.example",
        frequency_30d=18,
        engagement_score="0.080",
        waste_rate="0.560",
        confidence="0.860",
        decision_source="model",
        rationale=(
            "Daily digest you rarely open; HTTP-only unsubscribe (opens for you to finish)."
        ),
        http_urls=("http://medium.example/unsub/abc",),
        mailto=None,
        one_click=False,
        recent_subjects=("Today's highlights", "Recommended for you"),
    ),
    _SeedSender(
        sender_email="no-reply@social.example",
        sender_domain="social.example",
        frequency_30d=60,
        engagement_score="0.100",
        waste_rate="0.410",
        confidence="0.880",
        decision_source="rule",
        rationale=(
            "60 notifications in 30 days; mailto-only unsubscribe (finish in your mail client)."
        ),
        http_urls=(),
        mailto="mailto:unsubscribe@social.example?subject=unsubscribe",
        one_click=False,
        recent_subjects=("3 people liked your post", "You have 5 new notifications"),
    ),
    _SeedSender(
        sender_email="weekly@digest.example",
        sender_domain="digest.example",
        frequency_30d=25,
        engagement_score="0.150",
        waste_rate="0.720",
        confidence="0.810",
        decision_source="model",
        rationale="Noisy weekly digest with low engagement; supports one-click unsubscribe.",
        http_urls=("https://httpbin.org/status/200",),
        mailto=None,
        one_click=True,
        recent_subjects=("Your weekly roundup", "This week in tech"),
    ),
)


def _content_cipher(settings: Settings) -> object | None:
    """Build the content envelope cipher exactly as the API does (or None).

    Args:
        settings: Loaded application settings.

    Returns:
        An ``EnvelopeCipher`` bound to the content CMK when configured, else
        ``None`` (pass-through plaintext — matches the API's no-alias path).
    """
    if not settings.content_key_alias:
        return None
    import boto3  # noqa: PLC0415 - optional dependency only needed when KMS is configured

    from app.core.security import EnvelopeCipher  # noqa: PLC0415

    return EnvelopeCipher(key_id=settings.content_key_alias, client=boto3.client("kms"))


async def _seed() -> None:
    """Reset + seed the demo user and print a login cookie."""
    settings = get_settings()
    if not settings.session_signing_key:
        raise SystemExit("session_signing_key is not configured — set it in .env first.")
    cipher = _content_cipher(settings)
    classifications = ClassificationsRepo(cipher=cipher)  # type: ignore[arg-type]
    summaries = SummariesRepo(cipher=cipher)  # type: ignore[arg-type]
    unsubscribes = UnsubscribeSuggestionsRepo(cipher=cipher)  # type: ignore[arg-type]

    factory = get_sessionmaker()
    now = utcnow()
    async with factory() as session:
        # Idempotent: fully reset the dedicated demo user (cascades clean up).
        existing = (
            (await session.execute(select(User).where(User.email == DEMO_EMAIL))).scalars().first()
        )
        if existing is not None:
            await session.delete(existing)
            await session.flush()

        user = User(email=DEMO_EMAIL, tz="America/New_York", status="active")
        session.add(user)
        await session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            email=DEMO_EMAIL,
            status="active",
        )
        session.add(account)
        await session.flush()

        session.add(
            DigestRun(
                user_id=user.id,
                status="complete",
                trigger_type="scheduled",
                started_at=now - timedelta(hours=1),
                completed_at=now - timedelta(minutes=55),
                stats={"ingested": 5, "classified": 5, "summarized": 3, "new_must_read": 2},
                cost_cents=12,
            ),
        )

        for index, spec in enumerate(_EMAILS):
            email = Email(
                account_id=account.id,
                gmail_message_id=spec.gmail_id,
                thread_id=f"thread-{spec.gmail_id}",
                internal_date=now - timedelta(hours=index + 2),
                from_addr=spec.from_addr,
                to_addrs=[DEMO_EMAIL],
                cc_addrs=[],
                subject=spec.subject,
                snippet=spec.subject,
                labels=["UNREAD", "INBOX"],
                list_unsubscribe=None,
                content_hash=hashlib.sha256(spec.gmail_id.encode()).digest(),
                size_bytes=2048,
            )
            session.add(email)
            await session.flush()
            await classifications.upsert(
                session,
                ClassificationWrite(
                    email_id=email.id,
                    label=spec.bucket,
                    score=Decimal(spec.score),
                    rubric_version=1,
                    prompt_version_id=None,
                    decision_source=spec.decision_source,
                    model="" if spec.decision_source == "rule" else "gemini-1.5-flash",
                    tokens_in=0,
                    tokens_out=0,
                    is_newsletter=spec.bucket == "good_to_read",
                    reasons={"reasons": list(spec.reasons)},
                    user_id=user.id,
                    needs_review=spec.needs_review,
                ),
            )
            if spec.summary is not None:
                await summaries.upsert_email(
                    session,
                    SummaryEmailWrite(
                        email_id=email.id,
                        user_id=user.id,
                        prompt_version_id=None,
                        model="gemini-1.5-flash",
                        tokens_in=0,
                        tokens_out=0,
                        body_md=spec.summary,
                        entities=(),
                        confidence=Decimal("0.90"),
                        cache_hit=False,
                        batch_id=None,
                    ),
                )

        for sender in _SENDERS:
            await unsubscribes.upsert(
                session,
                UnsubscribeSuggestionWrite(
                    account_id=account.id,
                    user_id=user.id,
                    sender_domain=sender.sender_domain,
                    sender_email=sender.sender_email,
                    frequency_30d=sender.frequency_30d,
                    engagement_score=Decimal(sender.engagement_score),
                    waste_rate=Decimal(sender.waste_rate),
                    list_unsubscribe={
                        "http_urls": list(sender.http_urls),
                        "mailto": sender.mailto,
                        "one_click": sender.one_click,
                    },
                    confidence=Decimal(sender.confidence),
                    decision_source=sender.decision_source,
                    rationale=sender.rationale,
                    prompt_version_id=None,
                    model="" if sender.decision_source == "rule" else "gemini-1.5-flash",
                    tokens_in=0,
                    tokens_out=0,
                    last_email_at=now - timedelta(hours=3),
                    recent_subjects=sender.recent_subjects,
                ),
            )

        await session.commit()
        cookie = sign_cookie({"user_id": str(user.id)}, secret=settings.session_signing_key)

    print("\n=== Briefed local demo seeded ===")
    print(f"  demo user : {DEMO_EMAIL}")
    print(f"  emails    : {len(_EMAILS)} (across must_read / good_to_read / ignore)")
    print(f"  senders   : {len(_SENDERS)} unsubscribe suggestions")
    print("\nLog in as the demo user WITHOUT Google OAuth:")
    print("  1. Start the app:  make dev   (frontend at http://localhost:5173)")
    print("  2. Open http://localhost:5173, then in the browser DevTools console run:")
    print(f"       document.cookie = '{SESSION_COOKIE_NAME}={cookie}; path=/';")
    print("  3. Reload the page — you are now the demo user.")
    print("\n(Re-running this script resets the demo user's data.)\n")


if __name__ == "__main__":
    asyncio.run(_seed())
