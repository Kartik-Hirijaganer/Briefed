"""Per-stage handler modules invoked by :mod:`app.lambda_worker`.

Each handler is a pure-ish function ``(message: StageMessage, deps:
HandlerDeps) -> StageResult`` so it can be exercised directly in unit
tests without the SQS envelope.
"""
