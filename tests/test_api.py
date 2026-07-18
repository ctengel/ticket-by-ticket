"""Integration tests for the FastAPI game server (tkt_by_tkt.server)"""

import pytest
from fastapi.testclient import TestClient

from tkt_by_tkt import server

client = TestClient(server.app)

MAP = {
    "cities": {"A": [0, 0], "B": [0, 1], "C": [1, 1], "D": [1, 0]},
    "routes": [
        {"cities": ["A", "B"], "length": 2, "tracks": ["blue", "red"]},
        {"cities": ["B", "C"], "length": 1, "tracks": ["blank"]},
        {"cities": ["C", "D"], "length": 3, "tracks": ["green"]},
    ],
    "tickets": [
        {"cities": ["A", "B"], "points": 4},
        {"cities": ["C", "D"], "points": 6},
        {"cities": ["A", "C"], "points": 9},
    ],
}


def auth(token):
    return {"Authorization": "Bearer %s" % token}


def new_game(options=None, tbt_map=None):
    body = {"map": tbt_map or MAP}
    if options:
        body["options"] = options
    response = client.post("/v1/games", json=body)
    assert response.status_code == 201
    return response.json()["game_id"]


def join(game_id, name):
    response = client.post("/v1/games/%s/players" % game_id,
                           json={"name": name, "kind": "bot"})
    assert response.status_code == 201
    return response.json()


def test_create_rejects_unplayable_map():
    response = client.post("/v1/games", json={
        "map": {"cities": {"A": [0, 0], "B": [0, 1]},
                "routes": [{"cities": ["A", "B"]}]}})
    assert response.status_code == 422
    assert response.json()["error"] == "map_not_playable"


def test_malformed_body_uses_error_shape():
    response = client.post("/v1/games", json={"not_a_map": True})
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_unknown_game_404s():
    assert client.get("/v1/games/nope").status_code == 404
    assert client.get("/v1/games/nope/log").status_code == 404


def test_auth_ladder():
    game_id = new_game()
    seat_one = join(game_id, "Ada")
    seat_two = join(game_id, "Bea")
    url = "/v1/games/%s/players/%s" % (game_id, seat_one["player_id"])
    assert client.get(url).status_code == 401
    assert client.get(url, headers=auth("bogus")).status_code == 401
    forbidden = client.get(url, headers=auth(seat_two["token"]))
    assert forbidden.status_code == 403
    response = client.get(url, headers=auth(seat_one["token"]))
    assert response.status_code == 200
    private = response.json()
    assert private["hand"] == [] and private["tickets"] == []
    # a start before two join, or by an outsider, is refused
    lonely = new_game()
    seat = join(lonely, "Solo")
    response = client.post("/v1/games/%s/start" % lonely,
                           headers=auth(seat["token"]))
    assert response.status_code == 409


def test_etag_polling_and_map():
    game_id = new_game()
    response = client.get("/v1/games/%s" % game_id)
    assert response.status_code == 200
    etag = response.headers["etag"]
    assert etag == '"%d"' % response.json()["state_version"]
    cached = client.get("/v1/games/%s" % game_id,
                        headers={"If-None-Match": etag})
    assert cached.status_code == 304
    join(game_id, "Ada")  # any mutation changes the ETag
    fresh = client.get("/v1/games/%s" % game_id,
                       headers={"If-None-Match": etag})
    assert fresh.status_code == 200
    board = client.get("/v1/games/%s/map" % game_id).json()
    assert board["cities"] == MAP["cities"]


def test_full_game():
    game_id = new_game(options={"starting_cars": 4, "ticket_offer": 3})
    seat_one = join(game_id, "Ada")
    seat_two = join(game_id, "Bea")
    one, two = auth(seat_one["token"]), auth(seat_two["token"])

    response = client.post("/v1/games/%s/start" % game_id, headers=one)
    assert response.status_code == 200
    state = response.json()
    # p1's setup offer took all 3 tickets; p2 was auto-resolved
    assert state["phase"] == "setup"
    assert state["expecting"] == "setup_ticket_keeps"

    private = client.get("/v1/games/%s/players/%s"
                         % (game_id, seat_one["player_id"]),
                         headers=one).json()
    offered = [ticket["ticket_id"] for ticket in private["pending_offer"]]
    assert len(offered) == 3
    response = client.post("/v1/games/%s/ticket-keeps" % game_id,
                           headers=one, json={"tickets": offered})
    assert response.status_code == 201
    assert len(response.json()["kept"]) == 3

    state = client.get("/v1/games/%s" % game_id).json()
    assert state["phase"] == "active"
    assert state["current_player"] == seat_one["player_id"]

    # acting out of turn is a 409; drawing from an empty ticket deck a 422
    assert client.post("/v1/games/%s/card-draws" % game_id, headers=two,
                       json={"source": "deck"}).status_code == 409
    assert client.post("/v1/games/%s/ticket-draws" % game_id,
                       headers=one).json()["error"] == "ticket_deck_empty"

    # rig p1's hand (white-box into the store) for a deterministic claim
    game = server.GAMES[game_id]
    game.players[0].hand = ["blue", "blue"]
    response = client.post("/v1/games/%s/claims" % game_id, headers=one,
                           json={"route": "A|B", "track": 0,
                                 "cards": ["blue", "blue"]})
    assert response.status_code == 201
    assert response.json() == {"points": 2, "cars_remaining": 2}

    # 4 starting cars - 2 spent = 2 -> last round; Bea gets one more turn
    state = client.get("/v1/games/%s" % game_id).json()
    assert state["phase"] == "last_round"
    assert state["claims"] == [{"route": "A|B", "track": 0,
                                "player": seat_one["player_id"]}]
    for expected_remaining in (1, 0):
        response = client.post("/v1/games/%s/card-draws" % game_id,
                               headers=two, json={"source": "deck"})
        assert response.status_code == 201
        assert response.json()["draws_remaining"] == expected_remaining

    state = client.get("/v1/games/%s" % game_id).json()
    assert state["phase"] == "finished"
    scores = {line["player_id"]: line for line in state["scores"]}
    ada = scores[seat_one["player_id"]]
    # route 2, ticket A|B +4, C|D and A|C missed -15, longest path +10
    assert ada == {"player_id": seat_one["player_id"], "route_points": 2,
                   "tickets_gained": 4, "tickets_lost": 15,
                   "longest_path_bonus": 10, "total": 1}
    assert scores[seat_two["player_id"]]["total"] == 0
    # finished games reveal hands and tickets publicly
    assert all("hand" in p and "tickets" in p for p in state["players"])

    # the log hides deck cards but shows claim cards, and ?since filters
    log = client.get("/v1/games/%s/log" % game_id).json()
    assert log[-1]["type"] == "game_end"
    deck_draws = [e for e in log if e["type"] == "card_draw"]
    assert deck_draws and all("card" not in e for e in deck_draws)
    claim = next(e for e in log if e["type"] == "claim")
    assert claim["cards"] == ["blue", "blue"]
    tail = client.get("/v1/games/%s/log" % game_id,
                      params={"since": log[-2]["seq"]}).json()
    assert tail == [log[-1]]

    # and the game is over: further actions conflict
    assert client.post("/v1/games/%s/card-draws" % game_id, headers=two,
                       json={"source": "deck"}).status_code == 409


def test_wild_second_draw_rejected_over_http():
    game_id = new_game(tbt_map={k: v for k, v in MAP.items() if k != "tickets"})
    seat_one = join(game_id, "Ada")
    join(game_id, "Bea")
    one = auth(seat_one["token"])
    client.post("/v1/games/%s/start" % game_id, headers=one)
    game = server.GAMES[game_id]
    game.faceup = ["blue", "red", "green", "black", "white"]
    response = client.post("/v1/games/%s/card-draws" % game_id, headers=one,
                           json={"source": "faceup", "card": "blue"})
    assert response.status_code == 201
    game.faceup = ["wild", "red", "green", "black", "white"]
    response = client.post("/v1/games/%s/card-draws" % game_id, headers=one,
                           json={"source": "faceup", "card": "wild"})
    assert response.status_code == 422
    assert response.json()["error"] == "wild_needs_full_draw"
