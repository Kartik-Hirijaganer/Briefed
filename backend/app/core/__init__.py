"""Cross-cutting primitives — config, logging, security, errors, ids.

Modules in :mod:`app.core` are imported by most of the app; they have
zero business logic and never import from :mod:`app.services` or
:mod:`app.api` so the dependency graph stays one-way.
"""
