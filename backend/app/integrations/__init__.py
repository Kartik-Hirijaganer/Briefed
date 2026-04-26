"""External-service client adapters (AWS, LLMs, mailboxes).

Nothing in ``integrations`` is business logic. Each module is a thin
boundary over a third-party SDK — tests mock these modules rather than
the underlying SDK so the production code is exercised end-to-end.
"""
