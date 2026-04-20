"""Prompt-registry service (plan §6, §14 Phase 2).

Exposes :class:`app.services.prompts.registry.PromptRegistry` which
loads every ``packages/prompts/<key>/v<n>.md`` file, parses the YAML
frontmatter, and indexes them by ``(name, version)``. The registry is
used by the LLM client and by the eval harness so both see the same
prompt bundle.
"""

from app.services.prompts.registry import (
    PromptBundleError,
    PromptRegistry,
    RegisteredPrompt,
    default_prompt_root,
)

__all__ = [
    "PromptBundleError",
    "PromptRegistry",
    "RegisteredPrompt",
    "default_prompt_root",
]
