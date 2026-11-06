"""JSONL logging of every frame, event and recommendation + fixture recording."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"
FIXTURES_DIR = ROOT / "fixtures"


class _Jsonl:
    def __init__(self, path: Path):
        self.path = path
        self._f = None

    def write(self, obj: dict) -> None:
        if self._f is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._f = self.path.open("a", encoding="utf-8")
        self._f.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
        self._f.flush()

    def close(self) -> None:
        if self._f:
            self._f.close()
            self._f = None


class SessionLog:
    """logs/session-YYYYmmdd-HHMMSS/{frames,events,advice}.jsonl"""

    def __init__(self, root: Path = LOGS_DIR, enabled: bool = True):
        self.enabled = enabled
        self.dir = root / time.strftime("session-%Y%m%d-%H%M%S")
        self.frames = _Jsonl(self.dir / "frames.jsonl")
        self.events = _Jsonl(self.dir / "events.jsonl")
        self.advice = _Jsonl(self.dir / "advice.jsonl")

    def frame(self, f: dict) -> None:
        if self.enabled:
            self.frames.write(f)

    def event(self, e: dict, source: str) -> None:
        if self.enabled:
            self.events.write({"ts": time.time(), "source": source, **e})

    def advice_given(self, a: dict, shoe: dict) -> None:
        if self.enabled:
            self.advice.write({"ts": time.time(), "tc": shoe.get("true_count"),
                               "rc": shoe.get("running_count"), **a})

    def close(self) -> None:
        for j in (self.frames, self.events, self.advice):
            j.close()


class Recorder:
    """Raw frames -> fixtures/shoe_NNN.jsonl (parser test fixtures)."""

    def __init__(self, root: Path = FIXTURES_DIR):
        self.root = root
        self.out: _Jsonl | None = None
        self.count = 0

    @property
    def active(self) -> bool:
        return self.out is not None

    def next_path(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        nums = [int(m.group(1)) for p in self.root.glob("shoe_*.jsonl")
                if (m := re.match(r"shoe_(\d+)\.jsonl$", p.name))]
        return self.root / f"shoe_{(max(nums) + 1) if nums else 1:03d}.jsonl"

    def start(self, path: Path | None = None) -> Path:
        self.stop()
        p = path or self.next_path()
        self.out = _Jsonl(p)
        self.count = 0
        return p

    def write(self, frame: dict) -> None:
        if self.out:
            self.out.write(frame)
            self.count += 1

    def stop(self) -> None:
        if self.out:
            self.out.close()
            self.out = None

    def status(self) -> dict:
        return {"recording": self.active, "file": str(self.out.path.name) if self.out else None,
                "frames": self.count}
