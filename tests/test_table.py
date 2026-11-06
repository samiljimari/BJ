from server.rules import Rules
from server.table import Table

R = Rules.load("infinite_blackjack")


def card(rank, kind="player", hand=0):
    return {"type": "card", "rank": rank, "target": {"kind": kind, "seat": "shared", "hand": hand}}


def test_round_flow_and_active_hand():
    t = Table(R)
    t.apply({"type": "shoe_change"})
    t.apply({"type": "round_start", "round_id": "1"})
    t.apply(card("T"))
    t.apply(card("6", "dealer"))
    t.apply(card("6"))
    seat, idx, h = t.active_hand()
    assert h.ranks == ["T", "6"] and idx == 0
    t.apply({"type": "decision", "seat": "shared", "hand": 0, "action": "stand"})
    assert t.active_hand() is None
    t.apply(card("K", "dealer"))
    assert t.round.phase == "dealer"
    assert t.shoe.running_count == -1 + 1 + 1 - 1
    assert t.from_shoe_start


def test_split_moves_second_card():
    t = Table(R)
    t.apply({"type": "round_start"})
    t.apply(card("8"))
    t.apply(card("5", "dealer"))
    t.apply(card("8"))
    t.apply({"type": "decision", "seat": "shared", "hand": 0, "action": "split"})
    hands = t.round.seats["shared"].hands
    assert [h.ranks for h in hands] == [["8"], ["8"]]
    assert t.active_hand() is None  # waiting for hand 0's second card
    t.apply(card("3", hand=0))
    assert t.active_hand()[1] == 0
    t.apply({"type": "decision", "seat": "shared", "hand": 0, "action": "double"})
    t.apply(card("T", hand=0))
    assert hands[0].done and hands[0].doubled
    t.apply(card("9", hand=1))
    assert t.active_hand()[1] == 1


def test_six_cards_finish_hand():
    t = Table(R)
    t.apply({"type": "round_start"})
    t.apply(card("2"))
    t.apply(card("T", "dealer"))
    for c in ("3", "2", "3", "A", "2"):
        t.apply(card(c))
    h = t.round.seats["shared"].hands[0]
    assert len(h.ranks) == 6 and h.done


def test_undo_replays_history():
    t = Table(R)
    t.apply({"type": "shoe_change"})
    t.apply({"type": "round_start"})
    t.apply(card("5"))
    t.apply(card("K", "dealer"))
    rc = t.shoe.running_count
    t.apply(card("4"))
    t.undo()
    assert t.shoe.running_count == rc and t.shoe.cards_seen == 2
    assert t.round.seats["shared"].hands[0].ranks == ["5"]


def test_auto_target_follows_deal_order():
    t = Table(R)
    tg = t.auto_target()
    assert tg["kind"] == "player" and tg.get("new_round")
    t.apply({"type": "round_start"})
    t.apply(card("9"))
    assert t.auto_target()["kind"] == "dealer"
    t.apply(card("7", "dealer"))
    assert t.auto_target()["kind"] == "player"
    t.apply(card("7"))
    assert t.auto_target() == {"kind": "player", "seat": "shared", "hand": 0}
    t.apply({"type": "decision", "seat": "shared", "hand": 0, "action": "stand"})
    assert t.auto_target()["kind"] == "dealer"
    t.apply(card("5", "dealer"))          # dealer 12 -> must draw
    assert t.auto_target()["kind"] == "dealer"
    t.apply(card("6", "dealer"))          # dealer 18 -> done, next card starts a new round
    assert t.auto_target().get("new_round")
    assert t.round_view()["phase"] == "ended"


def test_face_down_card_not_counted():
    t = Table(R)
    t.apply(card("?", "dealer"))
    t.apply({"type": "card", "rank": None, "target": {"kind": "burn"}})
    assert t.shoe.cards_seen == 0
