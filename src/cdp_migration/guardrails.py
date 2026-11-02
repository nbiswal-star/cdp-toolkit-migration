"""Switchable safety layers. Each layer can be turned off for the with versus without evaluation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Guardrails:
    fidelity_gate: bool = True       # verbatim fields must equal the source; differences block the record
    approval_gate: bool = True       # create_draft needs QA pass (or a person's approval) and a matching hash
    pii_gate: bool = True            # personal data or instruction-like text routes the record to a person
    draft_only: bool = True          # targets refuse any status other than draft
    max_tool_calls: int = 1000       # per agent run
    max_retries_per_tool: int = 2    # per activity and tool after an error
    max_llm_tokens: int = 3_000_000  # input plus output tokens per whole agent run (each activity session: 60k)
    allow_hosts: tuple[str, ...] = field(default=(
        "www.collaborativediscussionproject.com", "collaborativediscussionproject.com",
        "static.wixstatic.com", ".usrfiles.com", ".filesusr.com"))

    @classmethod
    def off(cls) -> "Guardrails":
        """Unguarded arm for evaluation only. Never use it against the real IF website."""
        return cls(fidelity_gate=False, approval_gate=False, pii_gate=False, draft_only=False,
                   max_tool_calls=10_000, max_retries_per_tool=10, max_llm_tokens=10**9)


EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
# Text that addresses an AI system or tries to change the workflow. Facilitation activities are full
# of ordinary imperatives ("Ask participants to..."), so the patterns target AI and publishing words.
INJECTION = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|rules)|disregard (the|your) (instructions|rules)"
    r"|you are (an? )?(ai|assistant|language model)|system prompt|as an ai\b"
    r"|(publish|set) (this|the) (page|post|activity) (live|to publish)|status\s*[:=]\s*publish)",
    re.I)
