from server.shoe import Shoe


def test_counts_and_true_count():
    s = Shoe(8)
    for r in ["2", "3", "4", "K", "A", "7"]:
        assert s.add(r)
    assert s.running_count == 1  # +1 +1 +1 -1 -1 0
    assert s.cards_seen == 6
    assert s.cards_left == 416 - 6
    assert abs(s.true_count - 1 / ((416 - 6) / 52)) < 1e-9
    assert s.remaining[9] == 127 and s.remaining[0] == 31


def test_undo_restores_state():
    s = Shoe(8)
    s.add("5")
    s.add("Q")
    assert s.remove_last() == 10
    assert s.running_count == 1 and s.cards_seen == 1 and s.remaining[9] == 128


def test_overflow_is_flagged_not_counted():
    s = Shoe(1)
    for _ in range(4):
        assert s.add("A")
    assert not s.add("A")
    assert s.cards_seen == 4
    assert not s.integrity_ok
    s.reset()
    assert s.integrity_ok and s.cards_seen == 0
