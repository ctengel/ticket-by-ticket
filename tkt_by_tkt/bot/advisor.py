"""Advisor mode: same brain, but the move is recommended, not made

The human shares their player id and token; we fetch exactly what the
auto runner would see and print what it would have done, with the
rationale and the runners-up. Exit codes: 0 advice given, 2 nothing to
advise on (not this player's move, or the game is over).
"""

import json
import time

from .moves import describe, move_dict
from .view import GameView


def _fetch_view(client, game_id, player_id, map_cache):
    state, _ = client.state(game_id)
    private = client.private(game_id, player_id)
    if "map" not in map_cache:
        map_cache["map"] = client.get_map(game_id)
    return GameView.build(state, private, map_cache["map"], player_id), state


def _render(view, decision, state, out):
    me = next((p for p in view.players if p["player_id"] == view.my_id), {})
    out("Recommendation for %s (%s) -- phase %s, expecting %s"
        % (view.my_id, me.get("name", "?"), view.phase,
           view.expecting or "setup ticket keep"))
    out("  %s" % describe(decision.move).upper())
    out("  why: %s" % decision.rationale)
    if decision.alternatives:
        out("  also considered:")
        for move, score, why in decision.alternatives:
            out("    - %-40s (score %.1f) %s" % (describe(move), score, why))


def _render_json(decision, out):
    out(json.dumps({
        "move": move_dict(decision.move),
        "rationale": decision.rationale,
        "score": decision.score,
        "alternatives": [{"move": move_dict(move), "score": score,
                          "why": why}
                         for move, score, why in decision.alternatives],
    }))


def advise_once(client, game_id, player_id, brain, rng, json_out=False,
                out=print):
    """Print one recommendation; 2 when there is no move to recommend"""
    map_cache = {}
    view, state = _fetch_view(client, game_id, player_id, map_cache)
    if view.phase == "finished":
        out("game %s is finished" % game_id)
        return 2
    if not view.is_my_move():
        out("nothing to advise: phase %s, %s to act (expecting %s)"
            % (view.phase, state.get("current_player") or "nobody",
               state.get("expecting") or "start"))
        return 2
    decision = brain.decide(view, rng)
    if json_out:
        _render_json(decision, out)
    else:
        _render(view, decision, state, out)
    return 0


def watch(client, game_id, player_id, brain, rng, poll_interval=2.0,
          json_out=False, out=print, sleep=time.sleep):
    """Keep advising: print a fresh recommendation whenever it's our move"""
    map_cache = {}
    etag = None
    advised_version = None
    while True:
        state, etag = client.state(game_id, etag)
        if state is None:
            sleep(poll_interval)
            continue
        if state["phase"] == "finished":
            out("game %s is finished" % game_id)
            return 0
        view = None
        if (state.get("current_player") == player_id
                or state["phase"] == "setup"):
            private = client.private(game_id, player_id)
            if "map" not in map_cache:
                map_cache["map"] = client.get_map(game_id)
            view = GameView.build(state, private, map_cache["map"], player_id)
        if (view is not None and view.is_my_move()
                and state["state_version"] != advised_version):
            decision = brain.decide(view, rng)
            if json_out:
                _render_json(decision, out)
            else:
                _render(view, decision, state, out)
            advised_version = state["state_version"]
        sleep(poll_interval)
