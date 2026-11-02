"""Custom agent tools and their registry.

Each tool is a plain Python function. Its docstring is sent to the model as the tool
description, and its type hints become the JSON input schema, so the docstring is exactly
what the agent reads. Rules stated in a docstring are also enforced in code.
Every tool takes a hidden `ctx` argument (ToolContext) that the model never sees.
"""
from __future__ import annotations

import inspect
import json
import re
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..adapters import TargetAdapter
from ..guardrails import Guardrails
from ..http import Fetcher
from ..state import StateStore


@dataclass
class ToolContext:
    fetcher: Fetcher
    adapter: TargetAdapter
    state: StateStore
    guardrails: Guardrails = field(default_factory=Guardrails)
    link_fetcher: Fetcher | None = None
    llm: Any = None
    out_dir: Path = Path("out")
    errors: dict[tuple[str, str], int] = field(default_factory=dict)
    allow_document_mode: bool = False   # only the `cdp new-activity` command turns this on, never the agent
    permalink_base: str = "/toolkit/activity/"


REGISTRY: dict[str, Callable[..., dict]] = {}


def tool(fn: Callable[..., dict]) -> Callable[..., dict]:
    REGISTRY[fn.__name__] = fn
    return fn


_PY_TO_JSON = {str: "string", int: "integer", bool: "boolean", float: "number"}


def _json_type(tp: Any) -> dict[str, Any]:
    origin = typing.get_origin(tp)
    args = [a for a in typing.get_args(tp) if a is not type(None)]
    if origin in (typing.Union, getattr(__import__("types"), "UnionType", None)) and len(args) == 1:
        return _json_type(args[0])
    if origin in (list, typing.List):
        return {"type": "array", "items": _json_type(args[0]) if args else {}}
    return {"type": _PY_TO_JSON.get(tp, "string")}


ACTIVITY_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,119}")
AGENT_HIDDEN = {"extract_activity": {"document_text"}}  # parameters the orchestrator agent never sees


def tool_schema(fn: Callable[..., dict], for_agent: bool = True) -> dict[str, Any]:
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    props, required = {}, []
    hidden = AGENT_HIDDEN.get(fn.__name__, set()) if for_agent else set()
    for name, p in sig.parameters.items():
        if name == "ctx" or name in hidden:
            continue
        props[name] = _json_type(hints.get(name, str))
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {"name": fn.__name__, "description": inspect.getdoc(fn) or "",
            "input_schema": {"type": "object", "properties": props, "required": required}}


def all_schemas(names: list[str] | None = None) -> list[dict[str, Any]]:
    return [tool_schema(REGISTRY[n]) for n in (names or REGISTRY)]


def call(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run one tool with retry limits. Errors come back as {"error": ...} so the agent can route them."""
    if name not in REGISTRY:
        return {"error": f"unknown tool {name}"}
    aid = args.get("activity_id")
    if aid is not None and not (isinstance(aid, str) and ACTIVITY_ID.fullmatch(aid)):
        return {"error": "activity_id must be lowercase letters, digits, and hyphens (as returned by crawl_toolkit)"}
    key = (name, str(args.get("activity_id", args.get("url", ""))))
    if ctx.errors.get(key, 0) > ctx.guardrails.max_retries_per_tool:
        return {"error": f"retry limit reached for {name} on {key[1]}; send to human review"}
    try:
        result = REGISTRY[name](ctx, **args)
    except TypeError as e:
        result = {"error": f"bad arguments: {e}"}
    except Exception as e:  # noqa: BLE001 - tools must never crash the agent loop
        result = {"error": f"{type(e).__name__}: {e}"}
    if "error" in result:
        ctx.errors[key] = ctx.errors.get(key, 0) + 1
    ctx.state.save()
    json.dumps(result)  # results must be JSON serializable for the model
    return result


# Register tools by importing their modules.
from . import inventory, extract, checks, publish  # noqa: E402,F401
