"""Evolution Infinite Blackjack parser - NOT IMPLEMENTED YET (needs Phase 0 recon).

The message format is unknown until real frames are recorded. Workflow:

1. Enable the extension on the game iframe's origin, start the server with
   ``--parser none --record`` and watch/play at least one full shoe.
2. Run ``python tools/recon.py fixtures/shoe_001.jsonl`` - it groups messages by
   type, shows samples and highlights fields that look like cards.
3. Identify the messages for: new round, card dealt (rank/suit + target player/dealer
   + hand index after splits), decision phase, round result, shoe change/shuffle.
4. Implement ``parse`` below to emit normalized events (see server/table.py), then
   add a test that replays the fixture and checks the card totals per shoe
   (8 x 52 = 416 minus the cards behind the cut card).

Rules for this parser:
* Only emit cards that are visible on the table (face up). A face-down hole card is
  emitted when it is turned over.
* Emit every card that comes out of the shoe - including hit cards that go to other
  players after we stood (the "cards after I stand" question in the notes).
* If frames are binary (protobuf/msgpack), decode in a helper module first.
"""

from __future__ import annotations

from .base import Parser


class EvolutionInfiniteParser(Parser):
    name = "evolution_infinite"

    def parse(self, frame: dict) -> list[dict]:
        # TODO(recon): map Evolution messages to normalized events.
        return []
