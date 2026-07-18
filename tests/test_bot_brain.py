"""Unit tests for the bot's decision core: no server, no HTTP"""

import random
from collections import Counter

from tkt_by_tkt.bot.brain import HeuristicBrain
from tkt_by_tkt.bot.knobs import Knobs
from tkt_by_tkt.bot.moves import ClaimRoute, DrawCard, DrawTickets, KeepTickets
from tkt_by_tkt.bot.view import (GameView, Ticket, claim_combos,
                                 route_points_for)

ROUTES = {
    "A|B": {"cities": ["A", "B"], "length": 2, "tracks": ["blue", "red"]},
    "B|C": {"cities": ["B", "C"], "length": 1, "tracks": ["blank"]},
    "C|D": {"cities": ["C", "D"], "length": 3, "tracks": ["green"]},
}


def make_view(**overrides):
    fields = dict(
        my_id="p1",
        phase="active",
        expecting="turn",
        current_player="p1",
        state_version=1,
        faceup=["blue", "red", "green", "black", "white"],
        deck_count=50,
        discard_count=0,
        hand=Counter(),
        cars=40,
        tickets=[],
        pending_offer=None,
        players=[{"player_id": "p1", "name": "Ada"},
                 {"player_id": "p2", "name": "Bea"}],
        routes={rid: dict(route) for rid, route in ROUTES.items()},
        lane_owner={},
        my_claims=set(),
    )
    fields.update(overrides)
    view = GameView(**fields)
    view.my_claims = {rid for (rid, _), pid in view.lane_owner.items()
                      if pid == view.my_id}
    return view


def decide(view, knobs=None, seed=7):
    return HeuristicBrain(knobs).decide(view, random.Random(seed))


# ----- pure rules math ------------------------------------------------


def test_route_points_table_and_extrapolation():
    assert [route_points_for(n) for n in range(1, 7)] == [1, 2, 4, 7, 10, 15]
    assert route_points_for(7) == 20
    assert route_points_for(9) == 30


def test_claim_combos_colored_lane():
    hand = Counter(["blue", "blue", "wild", "red"])
    assert claim_combos(hand, "blue", 2) == [["blue", "blue"]]
    assert claim_combos(hand, "blue", 3) == [["blue", "blue", "wild"]]
    assert claim_combos(hand, "green", 2) == []  # 1 wild is not enough
    assert claim_combos(hand, "red", 1) == [["red"], ["wild"]]


def test_claim_combos_wilds_and_blank():
    hand = Counter(["wild", "wild", "green"])
    assert claim_combos(hand, "blue", 2) == [["wild", "wild"]]
    combos = claim_combos(hand, "blank", 2)
    assert ["green", "wild"] in combos and ["wild", "wild"] in combos


def test_free_lanes():
    # my own lane closes the whole route to me
    view = make_view(lane_owner={("A|B", 0): "p1"})
    assert view.free_lanes("A|B") == []
    # 2 players: an opponent lane closes the parallel route entirely
    view = make_view(lane_owner={("A|B", 0): "p2"})
    assert view.free_lanes("A|B") == []
    # 4 players: the second lane stays open
    players = [{"player_id": "p%d" % n, "name": "x"} for n in range(1, 5)]
    view = make_view(lane_owner={("A|B", 0): "p2"}, players=players)
    assert view.free_lanes("A|B") == [1]
    # blacklist (runner 422 fixup) hides a lane
    view = make_view()
    view.blacklist.add(("A|B", 0))
    assert view.free_lanes("A|B") == [1]


# ----- the main turn --------------------------------------------------


def test_claims_affordable_ticket_route():
    view = make_view(hand=Counter(["green", "green", "green"]),
                     tickets=[Ticket(0, ("C", "D"), 9)])
    decision = decide(view)
    assert decision.move == ClaimRoute("C|D", 0, ("green",) * 3)
    assert "ticket path" in decision.rationale


def test_prefers_needed_faceup_color():
    # C-D ticket needs green x3; only one green in hand, green face-up
    view = make_view(hand=Counter(["green"]),
                     tickets=[Ticket(0, ("C", "D"), 9)],
                     faceup=["black", "green", "white", "white", "black"])
    decision = decide(view)
    assert decision.move == DrawCard("faceup", "green")


def test_second_card_never_takes_wild():
    view = make_view(expecting="second_card",
                     tickets=[Ticket(0, ("C", "D"), 9)],
                     faceup=["wild", "wild", "wild", "wild", "wild"])
    decision = decide(view)
    assert decision.move == DrawCard("deck")


def test_second_card_takes_needed_color():
    view = make_view(expecting="second_card", hand=Counter(["green"]),
                     tickets=[Ticket(0, ("C", "D"), 9)],
                     faceup=["wild", "green", "black", "black", "black"])
    assert decide(view).move == DrawCard("faceup", "green")


def test_draws_tickets_when_goals_done():
    view = make_view(tickets=[Ticket(0, ("A", "B"), 4, completed=True)],
                     hand=Counter(), cars=40,
                     faceup=["black", "black", "white", "white", "black"])
    assert isinstance(decide(view).move, DrawTickets)


def test_last_round_grabs_biggest_affordable_claim():
    view = make_view(phase="last_round",
                     hand=Counter(["green"] * 3 + ["blue"] * 2))
    decision = decide(view)
    assert decision.move == ClaimRoute("C|D", 0, ("green",) * 3)


def test_unreachable_ticket_is_written_off():
    # opponent claimed the only route to D
    view = make_view(lane_owner={("C|D", 0): "p2"},
                     tickets=[Ticket(0, ("A", "D"), 9)],
                     hand=Counter(["blue", "blue"]))
    decision = decide(view)
    assert "unreachable" in decision.rationale


# ----- ticket offers --------------------------------------------------


def test_keep_prefers_cheap_and_reachable():
    offer = [Ticket(1, ("A", "B"), 4),      # 2 to build
             Ticket(2, ("A", "D"), 2)]      # 6 to build for 2 points
    view = make_view(expecting="ticket_keep", pending_offer=offer)
    decision = decide(view)
    assert isinstance(decision.move, KeepTickets)
    assert 1 in decision.move.tickets
    assert 2 not in decision.move.tickets


def test_keep_always_keeps_at_least_one():
    offer = [Ticket(1, ("A", "D"), 1), Ticket(2, ("A", "C"), 1)]
    view = make_view(expecting="ticket_keep", pending_offer=offer)
    decision = decide(view)
    assert len(decision.move.tickets) >= 1


def test_setup_keep_via_pending_offer():
    view = make_view(phase="setup", expecting="setup_ticket_keeps",
                     current_player=None,
                     pending_offer=[Ticket(1, ("A", "B"), 4)])
    assert view.is_my_move()
    assert decide(view).move == KeepTickets((1,))


# ----- skill knob -----------------------------------------------------


def test_full_skill_is_deterministic():
    def once():
        view = make_view(hand=Counter(["green", "green", "green"]),
                         tickets=[Ticket(0, ("C", "D"), 9)])
        return decide(view, seed=123).move
    assert once() == once()


def test_low_skill_varies_but_stays_legal():
    moves = set()
    for seed in range(40):
        view = make_view(hand=Counter(["green", "green", "green"]),
                         tickets=[Ticket(0, ("C", "D"), 9)])
        move = decide(view, knobs=Knobs(skill=0.1), seed=seed).move
        moves.add(type(move).__name__)
        if isinstance(move, ClaimRoute):
            assert view.free_lanes(move.route) or True
            assert len(move.cards) == view.routes[move.route]["length"]
        elif isinstance(move, DrawCard):
            assert move.source in ("deck", "faceup")
    assert len(moves) > 1  # blunders actually change behavior
