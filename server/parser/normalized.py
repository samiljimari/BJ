from __future__ import annotations

from .base import Parser

NORMALIZED_TYPES = {"card", "round_start", "decision", "round_end", "shoe_change"}


class NormalizedParser(Parser):
    """Frames that already carry normalized events (JSON object or list of them)."""

    name = "normalized"

    def parse(self, frame: dict) -> list[dict]:
        if frame.get("dir", "in") != "in":
            return []
        msg = self.json(frame)
        if isinstance(msg, dict):
            msg = msg.get("events", [msg])
        if not isinstance(msg, list):
            return []
        return [e for e in msg if isinstance(e, dict) and e.get("type") in NORMALIZED_TYPES]
