"""Thin LLM wrapper. AnthropicLLM calls the Claude Messages API; ScriptedLLM replays fixed turns for tests."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MODEL = os.environ.get("CDP_MODEL", "claude-sonnet-4-5")


@dataclass
class LLMResponse:
    content: list[dict[str, Any]]          # blocks: {"type": "text", "text"} or {"type": "tool_use", "id", "name", "input"}
    stop_reason: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b["type"] == "text")


class AnthropicLLM:
    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 4096):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model, self.max_tokens = model, max_tokens

    def complete(self, system: str, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        kwargs: dict[str, Any] = {"model": self.model, "max_tokens": self.max_tokens,
                                  "system": system, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        r = self.client.messages.create(**kwargs)
        blocks = []
        for b in r.content:
            if b.type == "text":
                blocks.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        return LLMResponse(blocks, r.stop_reason, r.usage.input_tokens, r.usage.output_tokens)


@dataclass
class ScriptedLLM:
    """Returns pre-written responses in order. `calls` records what the model was sent."""
    responses: list[LLMResponse]
    calls: list[dict] = field(default_factory=list)

    def complete(self, system, messages, tools=None):
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        if not self.responses:
            return LLMResponse([{"type": "text", "text": "done"}], "end_turn")
        return self.responses.pop(0)


def from_env():
    """AnthropicLLM when ANTHROPIC_API_KEY is set, else None."""
    return AnthropicLLM() if os.environ.get("ANTHROPIC_API_KEY") else None
