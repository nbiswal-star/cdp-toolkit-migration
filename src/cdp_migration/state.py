"""Run state kept in state.json, so re-runs update the same drafts and never duplicate media.

Per activity it records the source hash, the Activity record, QA results, the hash that passed
QA, any human approval, and the target post ID. Media are keyed by SHA-256.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import Activity


@dataclass
class ActivityState:
    url: str | None = None
    source_hash: str | None = None
    record: dict[str, Any] | None = None          # raw Wix record (kept locally, never committed)
    document: str | None = None                   # source text for activities added through the update workflow
    commenter_names: list[str] = field(default_factory=list)
    activity: dict[str, Any] | None = None
    qa: dict[str, Any] = field(default_factory=dict)  # {"validate": {...}, "fidelity": {...}, "pii": {...}}
    qa_hash: str | None = None                      # Activity.content_hash() when every check passed
    human_approved_hash: str | None = None          # set only by a person through `cdp approve`
    post_id: int | str | None = None
    draft_url: str | None = None
    media: dict[str, str] = field(default_factory=dict)  # kind ('pdf', 'image') -> sha256 key
    links: dict[str, Any] = field(default_factory=dict)


class StateStore:
    def __init__(self, path: str | Path | None = "state.json"):
        self.path = Path(path) if path else None
        self.activities: dict[str, ActivityState] = {}
        self.media: dict[str, dict[str, Any]] = {}  # sha256 -> {"id":..., "url":..., "source": ...}
        if self.path and self.path.exists():
            raw = json.loads(self.path.read_text())
            self.activities = {k: ActivityState(**v) for k, v in raw.get("activities", {}).items()}
            self.media = raw.get("media", {})

    def get(self, activity_id: str) -> ActivityState:
        return self.activities.setdefault(activity_id, ActivityState())

    def activity(self, activity_id: str) -> Activity | None:
        st = self.activities.get(activity_id)
        return Activity.from_dict(st.activity) if st and st.activity else None

    def save(self) -> None:
        if not self.path:
            return
        data = {"activities": {k: vars(v) for k, v in self.activities.items()}, "media": self.media}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        tmp.replace(self.path)
