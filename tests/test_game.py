"""Unit tests for the tkt_by_tkt.game rules engine"""

import pytest

from tkt_by_tkt import game as gamelib


def base_map(**over):
    tbt_map = {
        "cities": {"A": [0, 0], "B": [0, 1], "C": [1, 1], "D": [1, 0]},
        "routes": [
            {"cities": ["A", "B"], "length": 2, "tracks": ["blue", "red"]},
            {"cities": ["B", "C"], "length": 1, "tracks": ["blank"]},
            {"cities": ["C", "D"], "length": 3, "tracks": ["green"]},
            {"cities": ["A", "D"], "length": 7, "tracks": ["random"]},
        ],
        "tickets": [
            {"cities": ["A", "C"], "points": 5},
            {"cities": ["B", "D"], "points": 6},
            {"cities": ["A", "D"], "points": 7},
        ],
    }
    tbt_map.update(over)
    return tbt_map


def make_game(players=2, options=None, tickets=True, keep_setup=True):
    """A started game with setup ticket offers resolved (keep one each)"""
    tbt_map = base_map() if tickets else base_map(tickets=[])
    game = gamelib.Game("test", tbt_map, options)
    for index in range(players):
        game.join("player%d" % index)
    game.start(game.players[0])
    if keep_setup:
        for player in game.players:
            if player.pending_offer:
                game.keep_tickets(player,
                                  [player.pending_offer[0]["ticket_id"]])
    return game


def force_turn(game, player):
    """White-box: make it this player's fresh turn"""
    game.current = game.players.index(player)
    game.expecting = "turn"
    game.draws_taken = 0


# ----- creation -------------------------------------------------------


@pytest.mark.parametrize("breakage", [
    {"cities": {}},
    {"routes": []},
    {"routes": [{"cities": ["A", "B"], "tracks": ["blue"]}]},          # no length
    {"routes": [{"cities": ["A", "B"], "length": 2}]},                 # no tracks
    {"routes": [{"cities": ["A", "Zzz"], "length": 2, "tracks": ["blue"]}]},
    {"routes": [{"cities": ["A", "B"], "length": 2, "tracks": ["blue"]},
                {"cities": ["B", "A"], "length": 1, "tracks": ["red"]}]},
    {"tickets": [{"cities": ["A", "Zzz"], "points": 5}]},
    {"tickets": [{"cities": ["A", "B"]}]},                             # no points
])
def test_unplayable_maps_rejected(breakage):
    with pytest.raises(gamelib.Illegal) as err:
        gamelib.Game("test", base_map(**breakage))
    assert err.value.code == "map_not_playable"


def test_random_lanes_resolved_at_creation():
    game = gamelib.Game("test", base_map())
    tracks = game.routes["A|D"]["tracks"]
    assert tracks[0] in gamelib.COLORS
    assert "random" not in str(game.map)


def test_route_points_table_and_extrapolation():
    game = gamelib.Game("test", base_map())
    assert [game.route_points_for(n) for n in range(1, 7)] == [1, 2, 4, 7, 10, 15]
    assert game.route_points_for(7) == 20
    assert game.route_points_for(15) == 60
    custom = gamelib.Game("test", base_map(),
                          {"route_points": [2, 4]})
    assert game is not custom
    assert custom.route_points_for(2) == 4
    assert custom.route_points_for(4) == 14


# ----- joining/starting -----------------------------------------------


def test_start_needs_two_players_and_join_locks():
    game = gamelib.Game("test", base_map())
    player = game.join("solo")
    with pytest.raises(gamelib.Conflict) as err:
        game.start(player)
    assert err.value.code == "not_enough_players"
    game.join("second")
    game.start(player)
    with pytest.raises(gamelib.Conflict):
        game.join("late")
    with pytest.raises(gamelib.Conflict):
        game.start(player)


def test_deck_composition_and_deal():
    game = make_game()
    total = (len(game.deck) + len(game.discard) + len(game.faceup)
             + sum(len(p.hand) for p in game.players))
    assert total == len(gamelib.COLORS) * gamelib.CARDS_PER_COLOR + gamelib.WILD_CARDS
    assert all(len(p.hand) == 4 for p in game.players)
    assert len(game.faceup) == 5


def test_setup_ticket_keeps_gate_play():
    game = make_game(keep_setup=False, options={"ticket_offer": 1})
    assert game.phase == "setup"
    assert game.expecting == "setup_ticket_keeps"
    first, second = game.players
    with pytest.raises(gamelib.Conflict):   # can't act during setup
        game.draw_card(first, "deck")
    game.keep_tickets(first, [t["ticket_id"] for t in first.pending_offer])
    with pytest.raises(gamelib.Conflict) as err:
        game.keep_tickets(first, [])       # already resolved, game still setup
    assert err.value.code == "no_pending_offer"
    game.keep_tickets(second, [second.pending_offer[0]["ticket_id"]])
    assert game.phase == "active"
    assert game.current_player() is first
    assert game.expecting == "turn"


def test_ticketless_map_starts_straight_to_active():
    game = make_game(tickets=False, keep_setup=False)
    assert game.phase == "active"
    with pytest.raises(gamelib.Illegal) as err:
        game.draw_tickets(game.players[0])
    assert err.value.code == "ticket_deck_empty"


# ----- drawing cards ---------------------------------------------------


def test_two_deck_draws_make_a_turn():
    game = make_game()
    first, second = game.players
    with pytest.raises(gamelib.Conflict) as err:
        game.draw_card(second, "deck")
    assert err.value.code == "not_your_turn"
    result = game.draw_card(first, "deck")
    assert result["draws_remaining"] == 1
    assert game.expecting == "second_card"
    with pytest.raises(gamelib.Conflict) as err:  # claims can't follow a draw
        game.claim(first, "B|C", 0, ["blue"])
    assert err.value.code == "pending_followup"
    result = game.draw_card(first, "deck")
    assert result["draws_remaining"] == 0
    assert game.current_player() is second


def test_faceup_wild_rules():
    game = make_game()
    first = game.players[0]
    game.faceup = ["wild", "blue", "red", "green", "black"]
    result = game.draw_card(first, "faceup", "wild")
    assert result["draws_remaining"] == 0          # wild is the whole draw
    assert game.current_player() is game.players[1]
    force_turn(game, first)
    game.faceup = ["wild", "blue", "red", "green", "black"]
    game.draw_card(first, "faceup", "blue")
    game.faceup = ["wild", "red", "green", "black", "white"]  # no purple, one wild
    with pytest.raises(gamelib.Illegal) as err:
        game.draw_card(first, "faceup", "wild")
    assert err.value.code == "wild_needs_full_draw"
    with pytest.raises(gamelib.Illegal) as err:
        game.draw_card(first, "faceup", "purple")
    assert err.value.code == "card_not_faceup"


def test_deck_reshuffles_discard():
    game = make_game()
    first = game.players[0]
    game.deck = []
    game.discard = ["blue", "red"]
    game.draw_card(first, "deck")
    assert not game.discard
    assert len(first.hand) == 5


def test_faceup_reshuffle_on_three_wilds():
    game = make_game()
    game.log = []
    game.faceup = ["wild", "wild", "wild", "blue", "red"]
    game.deck = ["blue", "red", "green", "black", "orange"] * 4
    game.discard = []
    game._faceup_wild_check()
    assert game.faceup.count("wild") <= 2
    assert any(e["type"] == "faceup_reshuffle" for e in game.log)


def test_faceup_reshuffle_loop_guard():
    game = make_game()
    game.faceup = ["wild"] * 5
    game.deck = ["wild"]
    game.discard = []
    game._faceup_wild_check()                      # must not loop forever
    assert game.faceup == ["wild"] * 5


# ----- claiming --------------------------------------------------------


def test_claim_validation_matrix():
    game = make_game()
    first = game.players[0]
    first.hand = ["blue", "blue", "wild", "green", "red"]
    bad_cases = [
        ("Nope|Zzz", 0, ["blue", "blue"], "unknown_route"),
        ("A|B", 5, ["blue", "blue"], "bad_track"),
        ("A|B", 0, ["blue"], "bad_cards"),                    # wrong count
        ("A|B", 0, ["blue", "red"], "bad_cards"),             # mixed colors
        ("A|B", 0, ["green", "green"], "cards_not_in_hand"),
        ("A|B", 0, ["red", "red"], "cards_not_in_hand"),      # only one red held
        ("A|B", 1, ["blue", "blue"], "bad_cards"),            # lane 1 is red
    ]
    for rid, track, cards, code in bad_cases:
        with pytest.raises(gamelib.Illegal) as err:
            game.claim(first, rid, track, cards)
        assert err.value.code == code, (rid, track, cards)
    first.cars = 1
    with pytest.raises(gamelib.Illegal) as err:
        game.claim(first, "A|B", 0, ["blue", "blue"])
    assert err.value.code == "not_enough_cars"
    first.cars = 45
    result = game.claim(first, "A|B", 0, ["blue", "wild"])    # wilds fill in
    assert result == {"points": 2, "cars_remaining": 43}
    assert game.claims == [{"route": "A|B", "track": 0, "player": "p1"}]


def test_blank_lane_takes_any_single_color():
    game = make_game()
    first = game.players[0]
    first.hand = ["purple", "black"]
    with pytest.raises(gamelib.Illegal):
        game.claim(first, "B|C", 0, ["purple", "black"])       # still one color
    game.claim(first, "B|C", 0, ["purple"])
    assert first.route_points == 1


def test_parallel_lane_rules():
    # 2 players < parallel_min_players: second lane is closed to everyone
    game = make_game()
    first, second = game.players
    first.hand = ["blue", "blue"]
    second.hand = ["red", "red"]
    game.claim(first, "A|B", 0, ["blue", "blue"])
    with pytest.raises(gamelib.Illegal) as err:
        game.claim(second, "A|B", 1, ["red", "red"])
    assert err.value.code == "route_closed"
    # with the option lowered, another player may take the other lane...
    game = make_game(options={"parallel_min_players": 2})
    first, second = game.players
    first.hand = ["blue", "blue", "red", "red"]
    second.hand = ["red", "red"]
    game.claim(first, "A|B", 0, ["blue", "blue"])
    with pytest.raises(gamelib.Illegal) as err:               # same lane twice
        game.claim(second, "A|B", 0, ["red", "red"])
    assert err.value.code == "lane_claimed"
    game.claim(second, "A|B", 1, ["red", "red"])
    # ...but the same player never may (one lane per route)
    game = make_game(options={"parallel_min_players": 2})
    first = game.players[0]
    first.hand = ["blue", "blue", "red", "red"]
    game.claim(first, "A|B", 0, ["blue", "blue"])
    force_turn(game, first)
    with pytest.raises(gamelib.Illegal) as err:
        game.claim(first, "A|B", 1, ["red", "red"])
    assert err.value.code == "one_lane_per_route"


# ----- tickets ----------------------------------------------------------


def test_ticket_draw_and_keep():
    # offer 1 each during setup, leaving one ticket in the deck to draw
    game = make_game(options={"ticket_offer": 1})
    first, second = game.players
    assert len(game.ticket_deck) == 1
    result = game.draw_tickets(first)
    offer = result["offer"]
    assert len(offer) == 1
    assert game.expecting == "ticket_keep"
    with pytest.raises(gamelib.Conflict):                     # draw again mid-keep
        game.draw_tickets(first)
    with pytest.raises(gamelib.Illegal) as err:
        game.keep_tickets(first, [])
    assert err.value.code == "keep_too_few"
    with pytest.raises(gamelib.Illegal) as err:
        game.keep_tickets(first, [999])
    assert err.value.code == "bad_ticket_ids"
    game.keep_tickets(first, [offer[0]["ticket_id"]])
    assert len(first.tickets) == 2                            # setup keep + this
    assert not game.ticket_deck
    assert game.current_player() is second                    # keep ends turn


# ----- game end and scoring ----------------------------------------------


def test_last_round_and_scoring():
    game = make_game(tickets=False)
    first, second = game.players
    first.cars = 3
    first.hand = ["purple"]
    game.claim(first, "B|C", 0, ["purple"])                   # cars 3 -> 2
    assert game.phase == "last_round"
    game.draw_card(second, "deck")
    game.draw_card(second, "deck")                            # last turn done
    assert game.phase == "finished"
    assert game.current_player() is None
    scores = {line["player_id"]: line for line in game.scores}
    assert scores["p1"]["route_points"] == 1
    assert scores["p1"]["longest_path_bonus"] == 10
    assert scores["p1"]["total"] == 11
    assert scores["p2"]["total"] == 0
    assert scores["p2"]["longest_path_bonus"] == 0            # no claims, no bonus
    assert game.log[-1]["type"] == "game_end"
    revealed = game.public_state()["players"][0]
    assert "hand" in revealed and "tickets" in revealed
    with pytest.raises(gamelib.Conflict):
        game.draw_card(second, "deck")


def test_ticket_connectivity_and_longest_path():
    game = make_game()
    first, second = game.players
    first.tickets = [dict(cities=["A", "C"], points=5, ticket_id=0),
                     dict(cities=["B", "D"], points=6, ticket_id=1)]
    second.tickets = []
    # first claims A-B and B-C: A..C connected, B..D not
    first.claimed = [("A|B", 0), ("B|C", 0)]
    first.route_points = 3
    # second claims the length-7 A-D route: longer single chain
    second.claimed = [("A|D", 0)]
    second.route_points = 20
    game._finish()
    scores = {line["player_id"]: line for line in game.scores}
    assert scores["p1"]["tickets_gained"] == 5
    assert scores["p1"]["tickets_lost"] == 6
    assert scores["p1"]["longest_path_bonus"] == 0            # 3 < 7
    assert scores["p1"]["total"] == 3 + 5 - 6
    assert scores["p2"]["longest_path_bonus"] == 10
    assert scores["p2"]["total"] == 30


def test_longest_path_walks_cycles_and_ties():
    game = make_game()
    first, second = game.players
    # all four routes form the cycle A-B-C-D-A: trail uses every edge
    first.claimed = [("A|B", 0), ("B|C", 0), ("C|D", 0), ("A|D", 0)]
    assert game._longest_path(first) == 2 + 1 + 3 + 7
    # a tie awards the bonus to both players
    first.claimed = [("A|B", 0)]
    second.claimed = [("A|B", 1)]
    game._finish()
    assert all(line["longest_path_bonus"] == 10 for line in game.scores)


def test_state_version_and_log():
    game = gamelib.Game("test", base_map())
    version = game.state_version
    game.join("one")
    assert game.state_version == version + 1
    game.join("two")
    events = game.log_since(0)
    assert [e["type"] for e in events] == ["join", "join"]
    assert [e["seq"] for e in events] == [1, 2]
    assert game.log_since(1) == events[1:]
