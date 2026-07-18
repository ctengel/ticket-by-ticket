"""Full-auto loop: poll the game, and play whenever it is our move

One step() is a single poll-and-maybe-move cycle so tests can drive two
runners in lock step with no threads or real sleeping. The runner also
absorbs the realities of a shared remote game: 409 races (someone moved
first), 422 rejections when an assumed option default is wrong, and
connection drops.
"""

import random
import time

from .client import ApiError
from .moves import (ClaimRoute, DrawCard, DrawTickets, KeepTickets, describe)
from .view import WILD, GameView


class BotStuck(Exception):
    """No move the bot can think of is accepted by the server"""


class Runner:

    def __init__(self, client, game_id, player_id, brain, poll_interval=1.0,
                 rng=None, sleep=time.sleep, log=print, debug=None):
        self.client = client
        self.game_id = game_id
        self.player_id = player_id
        self.brain = brain
        self.poll_interval = poll_interval
        self.rng = rng or random.Random()
        self.sleep = sleep
        self.log = log
        self.debug = debug or (lambda message: None)
        self.etag = None
        self.backoff = 1.0
        self.setup_resolved = False
        self._map = None

    def run(self):
        """Play until the game finishes"""
        while self.step():
            pass

    def step(self):
        """One poll-and-maybe-move cycle; False once the game is over"""
        try:
            state, self.etag = self.client.state(self.game_id, self.etag)
        except ApiError as error:
            if error.status == 404:
                self.log("game %s is gone: %s" % (self.game_id, error.message))
                return False
            raise
        except OSError as error:
            self.log("connection trouble (%s); retrying in %.0fs"
                     % (error, self.backoff))
            self.sleep(self.backoff)
            self.backoff = min(self.backoff * 2, 30.0)
            return True
        self.backoff = 1.0
        if state is None:  # 304: nothing changed
            self.sleep(self.poll_interval)
            return True
        if state["phase"] == "finished":
            self._report_scores(state)
            return False
        if not self._maybe_move(state):
            self.debug("waiting (phase %s, %s to act)"
                       % (state["phase"], state.get("current_player")))
            self.sleep(self.poll_interval)
        return True

    # ----- taking a move -----------------------------------------------

    def _maybe_move(self, state):
        """Move if the game awaits us; True when a move was attempted"""
        setup = state["phase"] == "setup"
        my_turn = (state.get("current_player") == self.player_id
                   and state.get("expecting") in ("turn", "second_card",
                                                 "ticket_keep"))
        if not my_turn and not (setup and not self.setup_resolved):
            return False
        private = self.client.private(self.game_id, self.player_id)
        if setup and "pending_offer" not in private:
            # not started yet, or our setup offer is already resolved
            self.setup_resolved = state.get("expecting") is not None
            return False
        view = GameView.build(state, private, self._get_map(), self.player_id)
        if not view.is_my_move():
            return False
        decision = self.brain.decide(view, self.rng)
        self.log("%s: %s -- %s" % (self.player_id, describe(decision.move),
                                   decision.rationale))
        self._execute(view, decision.move)
        if setup:
            self.setup_resolved = True
        return True

    def _get_map(self):
        if self._map is None:
            self._map = self.client.get_map(self.game_id)
        return self._map

    def _send(self, move):
        if isinstance(move, DrawCard):
            self.client.draw_card(self.game_id, move.source, move.card)
        elif isinstance(move, ClaimRoute):
            self.client.claim(self.game_id, move.route, move.track,
                              move.cards)
        elif isinstance(move, DrawTickets):
            self.client.draw_tickets(self.game_id)
        elif isinstance(move, KeepTickets):
            self.client.keep_tickets(self.game_id, move.tickets)
        else:
            raise ValueError("unknown move %r" % (move,))
        self.etag = None  # our move changed the state

    def _execute(self, view, move):
        try:
            self._send(move)
        except ApiError as error:
            if error.status == 409:
                # a race: someone moved first, or we replayed; re-poll
                self.debug("conflict (%s); refreshing" % error.code)
                self.etag = None
                return
            if error.status == 422:
                self._recover(view, move, error)
                return
            raise

    # ----- 422 recovery -------------------------------------------------

    def _recover(self, view, move, error):
        """The server disagreed on legality; adjust and try again once"""
        self.log("%s: rejected (%s): %s" % (self.player_id, error.code,
                                            error.message))
        if isinstance(move, KeepTickets):
            self._recover_keep(view, move, error)
            return
        if (isinstance(move, ClaimRoute)
                and error.code in ("lane_claimed", "route_closed",
                                   "one_lane_per_route")):
            view.blacklist.add((move.route, move.track))
            retry = self.brain.decide(view, self.rng).move
            if retry != move:
                try:
                    self._send(retry)
                    self.log("%s: instead %s" % (self.player_id,
                                                 describe(retry)))
                    return
                except ApiError as again:
                    if again.status != 422:
                        raise
        self._ladder(view)

    def _recover_keep(self, view, move, error):
        """Keeps can't fall back to other actions mid-offer"""
        if error.code == "keep_too_few" and view.pending_offer:
            extra = [t.ticket_id for t in view.pending_offer
                     if t.ticket_id not in move.tickets]
            if extra:
                retry = KeepTickets(tuple(move.tickets) + (extra[0],))
                try:
                    self._send(retry)
                    self.log("%s: instead %s" % (self.player_id,
                                                 describe(retry)))
                    return
                except ApiError as again:
                    if again.status != 422:
                        raise
        raise BotStuck("cannot resolve ticket offer: %s" % error.message)

    def _ladder(self, view):
        """Last-resort legal-move hunt before declaring ourselves stuck"""
        attempts = [DrawCard("deck")]
        attempts += [DrawCard("faceup", color)
                     for color in dict.fromkeys(view.faceup) if color != WILD]
        if WILD in view.faceup and view.expecting != "second_card":
            attempts.append(DrawCard("faceup", WILD))
        if view.expecting == "turn":
            attempts.append(DrawTickets())
        for move in attempts:
            try:
                self._send(move)
                self.log("%s: fallback %s" % (self.player_id, describe(move)))
                return
            except ApiError as error:
                if error.status != 422:
                    raise
        raise BotStuck("no legal move was accepted; "
                       "the game may be out of cards and claims")

    # ----- reporting -----------------------------------------------------

    def _report_scores(self, state):
        names = {p["player_id"]: p["name"] for p in state["players"]}
        self.log("game %s finished" % self.game_id)
        lines = sorted(state.get("scores") or [],
                       key=lambda line: -line["total"])
        for line in lines:
            self.log("  %-4s %-16s routes %3g  tickets +%g/-%g  "
                     "longest +%g  total %g"
                     % (line["player_id"], names.get(line["player_id"], "?"),
                        line["route_points"], line["tickets_gained"],
                        line["tickets_lost"], line["longest_path_bonus"],
                        line["total"]))
