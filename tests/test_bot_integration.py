"""Bot-vs-bot integration tests over the real FastAPI app

The fastapi TestClient is injected as the bot Client's session, so the
whole stack (brain -> client -> HTTP -> server -> rules engine) runs
in-process with no sockets and no requests dependency.
"""

import random

from fastapi.testclient import TestClient

from tkt_by_tkt import server
from tkt_by_tkt.bot.advisor import advise_once
from tkt_by_tkt.bot.brain import HeuristicBrain
from tkt_by_tkt.bot.client import ApiError, Client
from tkt_by_tkt.bot.runner import Runner

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


def new_client():
    return Client("", session=TestClient(server.app))


def new_game(options=None, tbt_map=None):
    response = TestClient(server.app).post(
        "/v1/games", json={"map": tbt_map or MAP,
                           "options": options or {}})
    assert response.status_code == 201
    return response.json()["game_id"]


def start(game_id, token):
    response = TestClient(server.app).post(
        "/v1/games/%s/start" % game_id,
        headers={"Authorization": "Bearer %s" % token})
    assert response.status_code == 200


def new_runner(game_id, name, seed, log=None):
    client = new_client()
    seat = client.join(game_id, name)
    runner = Runner(client, game_id, seat["player_id"], HeuristicBrain(),
                    rng=random.Random(seed), sleep=lambda seconds: None,
                    log=log or (lambda message: None))
    return runner


def play_out(game_id, *runners):
    """Lock-step both runners until each has seen the game finish"""
    alive = list(runners)
    for _ in range(600):
        alive = [runner for runner in alive if runner.step()]
        if not alive:
            break
    assert not alive, "game did not finish within the step budget"
    state, _ = new_client().state(game_id)
    return state


def test_two_bots_play_a_ticketed_game_to_the_end():
    lines = []
    game_id = new_game(options={"starting_cars": 4})
    ada = new_runner(game_id, "Ada", seed=1, log=lines.append)
    bea = new_runner(game_id, "Bea", seed=2, log=lines.append)
    start(game_id, ada.client.token)

    state = play_out(game_id, ada, bea)
    assert state["phase"] == "finished"
    assert state["scores"] and len(state["scores"]) == 2
    # both bots resolved their own setup offers (p1 got all 3 tickets here,
    # p2's empty offer auto-resolved) and every kept ticket is accounted for
    kept = sum(p["ticket_count"] for p in state["players"])
    assert kept >= 1
    totals = {line["player_id"]: line["total"] for line in state["scores"]}
    assert set(totals) == {ada.player_id, bea.player_id}
    # the runners logged their moves and the final score table
    assert any("finished" in line for line in lines)


def test_two_bots_finish_a_map_without_tickets():
    plain = {key: value for key, value in MAP.items() if key != "tickets"}
    game_id = new_game(options={"starting_cars": 4}, tbt_map=plain)
    ada = new_runner(game_id, "Ada", seed=3)
    bea = new_runner(game_id, "Bea", seed=4)
    start(game_id, ada.client.token)
    state = play_out(game_id, ada, bea)
    assert state["phase"] == "finished"
    assert all(line["tickets_gained"] == 0 and line["tickets_lost"] == 0
               for line in state["scores"])


def test_runner_waits_politely_before_start():
    game_id = new_game()
    ada = new_runner(game_id, "Ada", seed=5)
    # nothing to do yet: still setup, no offer dealt
    assert ada.step() is True
    state, _ = ada.client.state(game_id)
    assert state["phase"] == "setup"


def test_runner_survives_a_409_race():
    game_id = new_game(tbt_map={k: v for k, v in MAP.items()
                                if k != "tickets"})
    ada = new_runner(game_id, "Ada", seed=6)
    bea = new_runner(game_id, "Bea", seed=7)
    start(game_id, ada.client.token)
    stale, _ = ada.client.state(game_id)
    assert stale["current_player"] == ada.player_id
    # ada moves for real...
    assert ada.step() is True
    # ...then replays the stale state: the 409 must be absorbed, not raised
    ada.etag = "stale"
    assert ada._maybe_move(stale) is True
    fresh, _ = ada.client.state(game_id)
    assert fresh["phase"] != "finished"


def test_advisor_recommends_without_moving():
    game_id = new_game(options={"starting_cars": 4})
    ada_client = new_client()
    seat = ada_client.join(game_id, "Ada")
    bea_client = new_client()
    bea_client.join(game_id, "Bea")
    start(game_id, ada_client.token)

    before, _ = ada_client.state(game_id)
    output = []
    code = advise_once(ada_client, game_id, seat["player_id"],
                       HeuristicBrain(), random.Random(0),
                       out=output.append)
    assert code == 0
    assert any("Recommendation" in line for line in output)
    after, _ = ada_client.state(game_id)
    assert after["state_version"] == before["state_version"]  # looked, no touch

    # bea has no pending move during ada's setup keep
    output = []
    bea_state, _ = bea_client.state(game_id)
    bea_id = [p["player_id"] for p in bea_state["players"]
              if p["name"] == "Bea"][0]
    code = advise_once(bea_client, game_id, bea_id, HeuristicBrain(),
                       random.Random(0), out=output.append)
    assert code == 2


def test_client_raises_api_errors():
    client = new_client()
    try:
        client.state("nope")
    except ApiError as error:
        assert error.status == 404 and error.code == "game_not_found"
    else:
        assert False, "expected ApiError"
