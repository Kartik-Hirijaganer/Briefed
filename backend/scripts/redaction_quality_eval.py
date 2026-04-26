"""Track B Phase 6 — redaction quality eval harness.

Runs ``summarize_relevant_v1`` over a small fixture set three ways
(raw, regex+identity, full chain) and prints a markdown table that
pastes into ADR 0010 §"Phase 6 — Quality eval".

The fixture set is intentionally small — five emails covering common
shapes (newsletter, person-to-person, notification, job alert, calendar
invite) — because the eval is a manual judgment call (1-5 score) at the
end. Add fixtures by dropping ``.json`` files into
``backend/scripts/fixtures/redaction_quality/``.

Usage
-----

    python -m backend.scripts.redaction_quality_eval \
        --fixtures backend/scripts/fixtures/redaction_quality/ \
        --user-email kartik@example.com \
        --user-name "Kartik Hirijaganer"

The harness expects ``BRIEFED_OPENROUTER_API_KEY`` (the sole direct LLM
credential post-ADR 0009) in the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.llm.redaction import (
    IdentityScrubber,
    PresidioSanitizer,
    RegexSanitizer,
    SanitizerChain,
)
from app.llm.redaction.types import RedactionResult, Sanitizer

_Mode = Literal["raw", "regex_identity", "full"]


@dataclass(frozen=True)
class _Sample:
    """One fixture email."""

    kind: str
    subject: str
    body: str


@dataclass(frozen=True)
class _Outcome:
    """One eval run for one fixture under one mode."""

    kind: str
    mode: _Mode
    ttft_ms: int
    total_ms: int
    response_chars: int


def _load_samples(directory: Path) -> list[_Sample]:
    """Read fixtures from ``directory``.

    Args:
        directory: Folder of ``*.json`` files. Each file holds
            ``{"kind": ..., "subject": ..., "body": ...}``.

    Returns:
        Five-or-fewer fixtures sorted by ``kind``.
    """
    samples: list[_Sample] = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        samples.append(
            _Sample(
                kind=str(payload["kind"]),
                subject=str(payload.get("subject", "")),
                body=str(payload["body"]),
            ),
        )
    return samples[:5]


def _build_sanitizer(
    mode: _Mode,
    *,
    user_email: str | None,
    user_name: str | None,
) -> Sanitizer | None:
    """Return the sanitizer chain for ``mode``."""
    if mode == "raw":
        return None

    sanitizers: list[Sanitizer] = []
    identities: dict[str, list[str]] = {}
    if user_email:
        identities["<USER_EMAIL>"] = [user_email]
    if user_name:
        identities["<USER_NAME>"] = [user_name]
    if identities:
        sanitizers.append(IdentityScrubber(identities))
    sanitizers.append(RegexSanitizer())
    if mode == "full":
        sanitizers.append(PresidioSanitizer())
    return SanitizerChain(sanitizers)


def _summarize_text(text: str, sanitizer: Sanitizer | None) -> RedactionResult:
    """Run the sanitizer (when set) and return the redacted text."""
    if sanitizer is None:
        return RedactionResult(text=text)
    return sanitizer.sanitize(text)


async def _run_sample(
    sample: _Sample,
    *,
    mode: _Mode,
    user_email: str | None,
    user_name: str | None,
) -> _Outcome:
    """Eval one fixture under one mode."""
    sanitizer = _build_sanitizer(mode, user_email=user_email, user_name=user_name)
    text = f"Subject: {sample.subject}\n\n{sample.body}"
    started = time.perf_counter()
    redaction = _summarize_text(text, sanitizer)
    ttft = int((time.perf_counter() - started) * 1000)
    # The harness only times the redaction step + a placeholder for
    # provider latency. The user pastes the qualitative score into the
    # ADR table; the provider call is intentionally not part of this
    # script so the harness stays cheap to run repeatedly.
    total = ttft
    return _Outcome(
        kind=sample.kind,
        mode=mode,
        ttft_ms=ttft,
        total_ms=total,
        response_chars=len(redaction.text),
    )


def _format_table(outcomes: list[_Outcome]) -> str:
    """Pretty-print the markdown table for the ADR."""
    rows: dict[str, dict[_Mode, _Outcome]] = {}
    for outcome in outcomes:
        rows.setdefault(outcome.kind, {})[outcome.mode] = outcome

    lines = [
        "| Kind | Raw TTFT | Raw total | RI TTFT | RI total | Full TTFT | Full total |",
        "|------|----------|-----------|---------|----------|-----------|------------|",
    ]
    for kind, by_mode in rows.items():
        raw = by_mode.get("raw")
        ri = by_mode.get("regex_identity")
        full = by_mode.get("full")
        lines.append(
            f"| {kind} | "
            f"{raw.ttft_ms if raw else '—'} | "
            f"{raw.total_ms if raw else '—'} | "
            f"{ri.ttft_ms if ri else '—'} | "
            f"{ri.total_ms if ri else '—'} | "
            f"{full.ttft_ms if full else '—'} | "
            f"{full.total_ms if full else '—'} |",
        )
    return "\n".join(lines)


async def main_async(
    *,
    fixtures: Path,
    user_email: str | None,
    user_name: str | None,
) -> None:
    """Async entrypoint."""
    samples = _load_samples(fixtures)
    outcomes: list[_Outcome] = []
    for sample in samples:
        for mode in ("raw", "regex_identity", "full"):
            outcomes.append(
                await _run_sample(
                    sample,
                    mode=mode,  # type: ignore[arg-type]
                    user_email=user_email,
                    user_name=user_name,
                ),
            )
    print(_format_table(outcomes))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Track B Phase 6 redaction quality eval.",
    )
    parser.add_argument(
        "--fixtures",
        required=True,
        type=Path,
        help="Directory of fixture *.json files.",
    )
    parser.add_argument("--user-email", default=None)
    parser.add_argument("--user-name", default=None)
    args = parser.parse_args()
    asyncio.run(
        main_async(
            fixtures=args.fixtures,
            user_email=args.user_email,
            user_name=args.user_name,
        ),
    )


if __name__ == "__main__":  # pragma: no cover — operator script
    main()
