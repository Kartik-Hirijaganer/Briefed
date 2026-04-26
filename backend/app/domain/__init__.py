"""Domain primitives shared by services and integrations.

Modules here declare Pydantic value objects and ``Protocol`` seams that
decouple business logic from concrete providers (Gmail, KMS, SES, …).
Nothing in this package performs I/O.
"""
