"""LLM prompt-redaction package (Track B / ADR 0010).

Public surface:

* :class:`Sanitizer` / :class:`RedactionResult` — protocol + value object.
* :class:`RegexSanitizer` — zero-deps regex set (emails, phones, ...).
* :class:`IdentityScrubber` — user-specific token replacement.
* :class:`PresidioSanitizer` — Presidio-backed NER pass.
* :class:`SanitizerChain` — composition primitive.
* :func:`build_default_chain` — Briefed defaults; reads from settings.

The chain is wired into :class:`app.llm.client.LLMClient` so every
outbound prompt passes through redaction before reaching a provider.
"""

from __future__ import annotations

from app.llm.redaction.chain import SanitizerChain
from app.llm.redaction.identity import IdentityScrubber
from app.llm.redaction.presidio import PresidioSanitizer
from app.llm.redaction.regex_sanitizer import RegexSanitizer
from app.llm.redaction.types import RedactionResult, Sanitizer


def build_default_chain(
    *,
    user_email: str | None = None,
    user_name: str | None = None,
    user_id: str | None = None,
    aliases: tuple[str, ...] = (),
    email_aliases: tuple[str, ...] = (),
    presidio_enabled: bool = True,
) -> SanitizerChain:
    """Construct the Briefed default sanitizer chain.

    Order is identity → regex → presidio, per ADR 0010 §Decision.

    Args:
        user_email: User's primary email; folded into ``<USER_EMAIL>``.
        user_name: User's full / display name; folded into ``<USER_NAME>``.
        user_id: Opaque user-id; folded into ``<USER_ID>``.
        aliases: Additional aliases / nicknames; folded into
            ``<USER_NAME>`` so the same placeholder covers them.
        email_aliases: Additional email addresses; folded into
            ``<USER_EMAIL>``. Track C populates this from the user
            profile's ``email_aliases`` column.
        presidio_enabled: Track B Phase 6 escape hatch — when ``False``
            the chain runs only identity + regex.

    Returns:
        A :class:`SanitizerChain` ready to pass to ``LLMClient.call``.
    """
    identities: dict[str, list[str]] = {}
    email_candidates = [e for e in (user_email, *email_aliases) if e]
    if email_candidates:
        identities["<USER_EMAIL>"] = email_candidates
    name_candidates = [n for n in (user_name, *aliases) if n]
    if name_candidates:
        identities["<USER_NAME>"] = list(name_candidates)
    if user_id:
        identities["<USER_ID>"] = [user_id]

    sanitizers: list[Sanitizer] = []
    if identities:
        sanitizers.append(IdentityScrubber(identities))
    sanitizers.append(RegexSanitizer())
    if presidio_enabled:
        sanitizers.append(PresidioSanitizer())
    return SanitizerChain(sanitizers)


__all__ = [
    "IdentityScrubber",
    "PresidioSanitizer",
    "RedactionResult",
    "RegexSanitizer",
    "Sanitizer",
    "SanitizerChain",
    "build_default_chain",
]
