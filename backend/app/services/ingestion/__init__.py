"""Ingestion pipeline (plan §7 Ingestion pipeline).

Transforms the Pydantic boundary objects produced by
:class:`app.services.gmail.provider.GmailProvider` into rows on the
``emails`` + ``email_content_blobs`` tables. Dedup is the core
correctness guarantee — hence :mod:`app.services.ingestion.dedup` is a
100%-coverage target (plan §20.1).
"""
