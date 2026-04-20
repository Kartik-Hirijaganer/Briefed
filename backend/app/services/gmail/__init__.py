"""Gmail integration layer.

Modules
-------
* :mod:`app.services.gmail.parser` — MIME → :class:`EmailMessage` parser.
* :mod:`app.services.gmail.client` — Quota-aware REST client over the
  Gmail HTTP API (history + messages.get).
* :mod:`app.services.gmail.oauth` — OAuth authorization-code flow
  helpers (URL builder, callback exchange).
* :mod:`app.services.gmail.provider` — :class:`MailboxProvider`
  implementation that composes the above into the pipeline seam.
"""
