from __future__ import annotations

import base64
import json


class Parser:
    """Base parser: understands nothing (records frames only)."""

    name = "none"

    def __init__(self) -> None:
        self.frames_seen = 0
        self.events_out = 0

    def feed(self, frame: dict) -> list[dict]:
        """Consume one raw frame, return zero or more normalized events."""
        self.frames_seen += 1
        events = self.parse(frame)
        self.events_out += len(events)
        return events

    def parse(self, frame: dict) -> list[dict]:
        return []

    # helpers -------------------------------------------------------------
    @staticmethod
    def text(frame: dict) -> str | None:
        data = frame.get("data")
        if data is None:
            return None
        if frame.get("binary"):
            try:
                return base64.b64decode(data).decode("utf-8")
            except Exception:
                return None
        return data

    @staticmethod
    def json(frame: dict):
        t = Parser.text(frame)
        if t is None:
            return None
        try:
            return json.loads(t)
        except Exception:
            return None

    @staticmethod
    def raw_bytes(frame: dict) -> bytes:
        data = frame.get("data") or ""
        if frame.get("binary"):
            return base64.b64decode(data)
        return data.encode("utf-8")

    def status(self) -> dict:
        return {"parser": self.name, "frames_seen": self.frames_seen, "events_out": self.events_out}
