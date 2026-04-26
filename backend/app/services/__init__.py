"""Business-logic services.

Each subpackage owns one pipeline or capability (Gmail, ingestion,
classification, …). Services import from :mod:`app.core`,
:mod:`app.domain`, and :mod:`app.db`; they never import from each other.
"""
