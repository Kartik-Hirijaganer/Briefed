"""Pydantic boundary models for API + worker payloads.

Boundary layer between the HTTP / queue surface and the internal
service layer. Every request body, response body, and SQS message body
gets a Pydantic model here so the contract with the outside world is
one file away from the router / handler.
"""
