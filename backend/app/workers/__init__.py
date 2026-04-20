"""Worker handlers invoked by the Lambda SQS event source.

Each stage (ingest, classify, summarize, …) has its own module under
``handlers/``. Phase 1 ships the ``ingest`` and ``fanout`` handlers;
later phases layer classify + summarize + jobs + unsubscribe + digest
on top without touching this dispatch seam.
"""
