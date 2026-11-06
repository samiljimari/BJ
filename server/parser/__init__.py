"""Provider-specific parsers: raw WebSocket frames -> normalized events.

A raw frame (as forwarded by the browser extension and stored in fixtures):
  {"kind": "frame", "dir": "in"|"out", "url": "<ws url>", "socket": 3,
   "binary": false, "data": "<text, or base64 if binary>", "ts": 1730800000123,
   "frame_url": "<page url of the frame that owns the socket>"}

The parser is the ONLY provider-specific part; everything downstream works on
normalized events (see server/table.py).
"""

from __future__ import annotations

from .base import Parser
from .demo import DemoParser
from .evolution_infinite import EvolutionInfiniteParser
from .normalized import NormalizedParser

PARSERS: dict[str, type[Parser]] = {
    "none": Parser,
    "normalized": NormalizedParser,
    "demo": DemoParser,
    "evolution_infinite": EvolutionInfiniteParser,
}


def get_parser(name: str) -> Parser:
    try:
        return PARSERS[name]()
    except KeyError:
        raise SystemExit(f"unknown parser {name!r}; choose from {', '.join(PARSERS)}")
