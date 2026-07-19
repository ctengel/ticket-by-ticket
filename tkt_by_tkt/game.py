"""Server-side rules engine for playing a game (rules.md) on a TBT map

Pure game logic with no HTTP concepts beyond the error status codes that
design/api.md assigns to each failure class; the FastAPI layer in server.py
translates GameError subclasses into responses.
"""

import copy
import random
import secrets
from collections import Counter

# Concrete card/track colors (map.schema.json enum minus random/blank)
COLORS = ["blue", "red", "orange", "green", "yellow", "purple", "white", "black"]
WILD = "wild"
BLANK = "blank"
RANDOM = "random"

# rules.md fixes no deck composition; use the classic one
CARDS_PER_COLOR = 12
WILD_CARDS = 14

# Points for route lengths beyond the configured table continue at the
# table's final step (10 -> 15 is +5)
ROUTE_POINTS_STEP = 5
LONGEST_PATH_BONUS = 10

DEFAULT_OPTIONS = {
    "starting_cars": 45,
    "starting_hand": 4,
    "faceup_count": 5,
    "ticket_offer": 3,
    "ticket_keep_min": 1,
    "setup_ticket_keep_min": 1,
    "last_round_cars": 2,
    "parallel_min_players": 4,
    "route_points": [1, 2, 4, 7, 10, 15],
}


class GameError(Exception):
    """A rejected request; status per the api.md error ladder"""
    status = 500

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class NotFound(GameError):
    status = 404


class Conflict(GameError):
    status = 409


class Illegal(GameError):
    status = 422


def route_id(city_a, city_b):
    """Stable route ID: sorted city names joined with |"""
    return "|".join(sorted([city_a, city_b]))


class Player:
    """One seat at the table"""

    def __init__(self, player_id, name, kind, cars):
        self.player_id = player_id
        self.name = name
        self.kind = kind
        self.token = secrets.token_urlsafe(32)
        self.cars = cars
        self.hand = []
        self.tickets = []          # ticket dicts kept
        self.pending_offer = None  # list of ticket dicts, or None
        self.setup_resolved = False
        self.route_points = 0
        self.claimed = []          # (route_id, track) tuples

    def public(self):
        return {"player_id": self.player_id,
                "name": self.name,
                "kind": self.kind,
                "cars": self.cars,
                "hand_count": len(self.hand),
                "ticket_count": len(self.tickets),
                "claimed_routes": len(self.claimed)}


class Game:
    """Authoritative state of one game"""

    def __init__(self, game_id, map_dict, options=None):
        self.game_id = game_id
        self.options = dict(DEFAULT_OPTIONS)
        self.options.update(options or {})
        self.map = self._validate_map(map_dict)
        self.routes = {route_id(*r["cities"]): r for r in self.map["routes"]}
        self.players = []
        self.phase = "setup"
        self.started = False
        self.expecting = None        # turn | second_card | ticket_keep | setup_ticket_keeps
        self.current = None          # index into players
        self.draws_taken = 0
        self.deck = []
        self.discard = []
        self.faceup = []
        self.ticket_deck = []        # ticket dicts, top at index 0
        self.claims = []             # {"route", "track", "player"}
        self.claimed_lanes = {}      # (route_id, track) -> player_id
        self.final_turns = None      # countdown once last_round begins
        self.scores = None
        self.log = []
        self.state_version = 0

    # ----- creation ---------------------------------------------------

    def _validate_map(self, map_dict):
        resolved = copy.deepcopy(map_dict)

        def bad(why):
            return Illegal("map_not_playable", "map not playable: " + why)

        cities = resolved.get("cities")
        if not isinstance(cities, dict) or not cities:
            raise bad("no cities")
        routes = resolved.get("routes")
        if not isinstance(routes, list) or not routes:
            raise bad("no routes")
        seen = set()
        for route in routes:
            pair = route.get("cities")
            if not pair or len(pair) != 2 or pair[0] == pair[1]:
                raise bad("route needs two distinct cities")
            for city in pair:
                if city not in cities:
                    raise bad("route city %r not on map" % city)
            rid = route_id(*pair)
            if rid in seen:
                raise bad("duplicate route %s" % rid)
            seen.add(rid)
            length = route.get("length")
            if not isinstance(length, int) or length < 1:
                raise bad("route %s needs an integer length >= 1" % rid)
            tracks = route.get("tracks")
            if not tracks:
                raise bad("route %s needs at least one track" % rid)
            route["tracks"] = [random.choice(COLORS) if t == RANDOM else t
                               for t in tracks]
            for track in route["tracks"]:
                if track != BLANK and track not in COLORS:
                    raise bad("route %s has unknown color %r" % (rid, track))
        for ticket in resolved.get("tickets", []):
            pair = ticket.get("cities")
            if not pair or len(pair) != 2 or pair[0] == pair[1]:
                raise bad("ticket needs two distinct cities")
            for city in pair:
                if city not in cities:
                    raise bad("ticket city %r not on map" % city)
            if not isinstance(ticket.get("points"), (int, float)):
                raise bad("ticket %s needs points" % "|".join(pair))
        return resolved

    def route_points_for(self, length):
        """Points for a claimed route, extrapolating past the table"""
        table = self.options["route_points"]
        if length <= len(table):
            return table[length - 1]
        return table[-1] + ROUTE_POINTS_STEP * (length - len(table))

    # ----- small helpers ----------------------------------------------

    def _bump(self):
        self.state_version += 1

    def _log(self, event):
        event["seq"] = len(self.log) + 1
        self.log.append(event)

    def player_by_id(self, player_id):
        for player in self.players:
            if player.player_id == player_id:
                return player
        raise NotFound("player_not_found", "no player %s" % player_id)

    def player_by_token(self, token):
        for player in self.players:
            if token and secrets.compare_digest(player.token, token):
                return player
        return None

    def current_player(self):
        if self.current is None:
            return None
        return self.players[self.current]

    def _draw_deck_card(self):
        """Take the top deck card, reshuffling the discard in if needed"""
        if not self.deck and self.discard:
            self.deck = self.discard
            self.discard = []
            random.shuffle(self.deck)
        if not self.deck:
            return None
        return self.deck.pop()

    def _refill_faceup(self):
        while len(self.faceup) < self.options["faceup_count"]:
            card = self._draw_deck_card()
            if card is None:
                break
            self.faceup.append(card)
        self._faceup_wild_check()

    def _faceup_wild_check(self):
        """rules.md: 3+ face-up wilds discards and redeals the whole row"""
        while self.faceup.count(WILD) >= 3:
            pool = self.deck + self.discard + self.faceup
            row = min(self.options["faceup_count"], len(pool))
            non_wild = sum(1 for c in pool if c != WILD)
            if non_wild < row - 2:
                break  # the pool can never show fewer than 3 wilds
            self.discard.extend(self.faceup)
            self.faceup = []
            while len(self.faceup) < self.options["faceup_count"]:
                card = self._draw_deck_card()
                if card is None:
                    break
                self.faceup.append(card)
            self._log({"type": "faceup_reshuffle"})

    # ----- joining and starting ---------------------------------------

    def join(self, name, kind="human"):
        if self.started:
            raise Conflict("game_started", "cannot join a started game")
        player = Player("p%d" % (len(self.players) + 1), name, kind,
                        self.options["starting_cars"])
        self.players.append(player)
        self._log({"type": "join", "player": player.player_id})
        self._bump()
        return player

    def start(self, player):
        if self.started:
            raise Conflict("already_started", "game already started")
        if len(self.players) < 2:
            raise Conflict("not_enough_players", "need at least two players")
        self.started = True
        self.deck = ([color for color in COLORS for _ in range(CARDS_PER_COLOR)]
                     + [WILD] * WILD_CARDS)
        random.shuffle(self.deck)
        for each in self.players:
            for _ in range(self.options["starting_hand"]):
                card = self._draw_deck_card()
                if card is not None:
                    each.hand.append(card)
        self._refill_faceup()
        self.ticket_deck = [dict(ticket, ticket_id=index) for index, ticket
                            in enumerate(self.map.get("tickets", []))]
        random.shuffle(self.ticket_deck)
        for each in self.players:
            offer = self._deal_tickets()
            if offer:
                each.pending_offer = offer
            else:
                each.setup_resolved = True
        self._log({"type": "start", "player": player.player_id})
        if all(p.setup_resolved for p in self.players):
            self._begin_play()
        else:
            self.expecting = "setup_ticket_keeps"
        self._bump()

    def _deal_tickets(self):
        offer = self.ticket_deck[:self.options["ticket_offer"]]
        del self.ticket_deck[:len(offer)]
        return offer

    def _begin_play(self):
        self.phase = "active"
        self.current = 0
        self.expecting = "turn"
        self.draws_taken = 0

    # ----- turn plumbing ----------------------------------------------

    def _require_action(self, player, allowed_expecting):
        """The Conflict half of the api.md validation ladder"""
        if self.phase not in ("active", "last_round"):
            raise Conflict("wrong_phase",
                           "game is %s, not in play" % self.phase)
        if self.current_player() is not player:
            raise Conflict("not_your_turn", "it is not your turn")
        if self.expecting not in allowed_expecting:
            raise Conflict("pending_followup",
                           "game is expecting %s" % self.expecting)

    def _end_turn(self):
        player = self.current_player()
        if (self.phase == "active"
                and player.cars <= self.options["last_round_cars"]):
            self.phase = "last_round"
            self.final_turns = len(self.players) - 1
            self._log({"type": "last_round", "player": player.player_id})
        elif self.phase == "last_round":
            self.final_turns -= 1
            if self.final_turns <= 0:
                self._finish()
                return
        self.current = (self.current + 1) % len(self.players)
        self.expecting = "turn"
        self.draws_taken = 0

    # ----- actions -----------------------------------------------------

    def draw_card(self, player, source, card=None):
        self._require_action(player, ("turn", "second_card"))
        if source == "faceup":
            if card is None:
                raise Illegal("card_required",
                              "drawing face-up requires a card color")
            if card not in self.faceup:
                raise Illegal("card_not_faceup",
                              "%s is not in the face-up row" % card)
            if card == WILD and self.expecting == "second_card":
                raise Illegal("wild_needs_full_draw",
                              "a face-up wild must be the whole draw")
            self.faceup.remove(card)
            taken = card
            self._refill_faceup()
            self._log({"type": "card_draw", "player": player.player_id,
                       "source": "faceup", "card": taken})
        else:
            taken = self._draw_deck_card()
            if taken is None:
                raise Illegal("deck_empty", "draw and discard piles are empty")
            self._log({"type": "card_draw", "player": player.player_id,
                       "source": "deck"})
        player.hand.append(taken)
        self.draws_taken += 1
        wild_faceup = source == "faceup" and taken == WILD
        # end the turn early if no legal second draw exists (empty pool, or
        # only face-up wilds left, which can't be taken as a second card)
        no_more_cards = (not self.deck and not self.discard
                         and all(c == WILD for c in self.faceup))
        if self.draws_taken >= 2 or wild_faceup or no_more_cards:
            draws_remaining = 0
            self._end_turn()
        else:
            draws_remaining = 1
            self.expecting = "second_card"
        self._bump()
        return {"card": taken, "draws_remaining": draws_remaining}

    def claim(self, player, rid, track, cards):
        self._require_action(player, ("turn",))
        route = self.routes.get(rid)
        if route is None:
            raise Illegal("unknown_route", "no route %s" % rid)
        if not isinstance(track, int) or not 0 <= track < len(route["tracks"]):
            raise Illegal("bad_track", "route %s has no track %r" % (rid, track))
        if (rid, track) in self.claimed_lanes:
            raise Illegal("lane_claimed", "that lane is already claimed")
        if any(claimed_rid == rid for claimed_rid, _ in player.claimed):
            raise Illegal("one_lane_per_route",
                          "you already own a lane on %s" % rid)
        if (len(self.players) < self.options["parallel_min_players"]
                and any(key[0] == rid for key in self.claimed_lanes)):
            raise Illegal("route_closed",
                          "route closed: parallel lanes need %d+ players"
                          % self.options["parallel_min_players"])
        length = route["length"]
        if player.cars < length:
            raise Illegal("not_enough_cars",
                          "route needs %d cars, you have %d"
                          % (length, player.cars))
        if len(cards) != length:
            raise Illegal("bad_cards",
                          "route needs exactly %d cards" % length)
        spent = Counter(cards)
        if spent - Counter(player.hand):
            raise Illegal("cards_not_in_hand",
                          "those cards are not all in your hand")
        colors = set(cards) - {WILD}
        lane = route["tracks"][track]
        if len(colors) > 1:
            raise Illegal("bad_cards", "cards must be one color plus wilds")
        if lane != BLANK and colors and colors != {lane}:
            raise Illegal("bad_cards", "lane color is %s" % lane)
        for card in cards:
            player.hand.remove(card)
        self.discard.extend(cards)
        player.cars -= length
        points = self.route_points_for(length)
        player.route_points += points
        player.claimed.append((rid, track))
        self.claimed_lanes[(rid, track)] = player.player_id
        self.claims.append({"route": rid, "track": track,
                            "player": player.player_id})
        self._log({"type": "claim", "player": player.player_id, "route": rid,
                   "track": track, "cards": list(cards)})
        self._end_turn()
        self._bump()
        return {"points": points, "cars_remaining": player.cars}

    def draw_tickets(self, player):
        self._require_action(player, ("turn",))
        offer = self._deal_tickets()
        if not offer:
            raise Illegal("ticket_deck_empty", "no destination tickets left")
        player.pending_offer = offer
        self.expecting = "ticket_keep"
        self._log({"type": "ticket_draw", "player": player.player_id,
                   "offered": len(offer)})
        self._bump()
        return {"offer": offer}

    def keep_tickets(self, player, ticket_ids):
        setup_keep = self.phase == "setup"
        if setup_keep:
            if not self.started:
                raise Conflict("wrong_phase", "game has not started")
            if player.pending_offer is None:
                raise Conflict("no_pending_offer",
                               "your setup offer is already resolved")
            keep_min = self.options["setup_ticket_keep_min"]
        else:
            self._require_action(player, ("ticket_keep",))
            keep_min = self.options["ticket_keep_min"]
        offer = player.pending_offer
        by_id = {ticket["ticket_id"]: ticket for ticket in offer}
        wanted = set(ticket_ids)
        if wanted - set(by_id):
            raise Illegal("bad_ticket_ids",
                          "tickets must come from your pending offer")
        if len(wanted) < min(keep_min, len(offer)):
            raise Illegal("keep_too_few",
                          "must keep at least %d ticket(s)"
                          % min(keep_min, len(offer)))
        kept = [ticket for ticket in offer if ticket["ticket_id"] in wanted]
        returned = [t for t in offer if t["ticket_id"] not in wanted]
        self.ticket_deck.extend(returned)
        player.tickets.extend(kept)
        player.pending_offer = None
        self._log({"type": "ticket_keep", "player": player.player_id,
                   "kept": len(kept)})
        if setup_keep:
            player.setup_resolved = True
            if all(p.setup_resolved for p in self.players):
                self._begin_play()
        else:
            self._end_turn()
        self._bump()
        return {"kept": kept}

    # ----- game end and scoring ----------------------------------------

    def _finish(self):
        self.phase = "finished"
        self.current = None
        self.expecting = None
        longest = {p.player_id: self._longest_path(p) for p in self.players}
        best = max(longest.values())
        self.scores = []
        for player in self.players:
            gained = 0
            lost = 0
            for ticket in player.tickets:
                if self._connected(player, *ticket["cities"]):
                    gained += ticket["points"]
                else:
                    lost += ticket["points"]
            bonus = LONGEST_PATH_BONUS if (best and
                                           longest[player.player_id] == best) else 0
            self.scores.append({
                "player_id": player.player_id,
                "route_points": player.route_points,
                "tickets_gained": gained,
                "tickets_lost": lost,
                "longest_path_bonus": bonus,
                "total": player.route_points + gained - lost + bonus,
            })
        self._log({"type": "game_end"})

    def _player_edges(self, player):
        """Claimed lanes as (cityA, cityB, length) edges"""
        edges = []
        for rid, _ in player.claimed:
            route = self.routes[rid]
            edges.append((route["cities"][0], route["cities"][1],
                          route["length"]))
        return edges

    def _connected(self, player, city_a, city_b):
        adjacency = {}
        for one, two, _ in self._player_edges(player):
            adjacency.setdefault(one, set()).add(two)
            adjacency.setdefault(two, set()).add(one)
        frontier = [city_a]
        seen = {city_a}
        while frontier:
            here = frontier.pop()
            if here == city_b:
                return True
            for there in adjacency.get(here, ()):
                if there not in seen:
                    seen.add(there)
                    frontier.append(there)
        return False

    def _longest_path(self, player):
        """Longest edge-distinct trail through the player's claims"""
        edges = self._player_edges(player)
        adjacency = {}
        for index, (one, two, _) in enumerate(edges):
            adjacency.setdefault(one, []).append((index, two))
            adjacency.setdefault(two, []).append((index, one))

        def walk(city, used):
            best = 0
            for index, there in adjacency.get(city, ()):
                if index not in used:
                    best = max(best,
                               edges[index][2] + walk(there, used | {index}))
            return best

        return max((walk(city, frozenset()) for city in adjacency), default=0)

    # ----- views ---------------------------------------------------------

    def public_state(self):
        finished = self.phase == "finished"
        players = []
        for player in self.players:
            info = player.public()
            if finished:
                info["hand"] = list(player.hand)
                info["tickets"] = [self._ticket_view(player, t)
                                   for t in player.tickets]
            players.append(info)
        state = {"game_id": self.game_id,
                 "state_version": self.state_version,
                 "phase": self.phase,
                 "current_player": (self.current_player().player_id
                                    if self.current_player() else None),
                 "faceup": list(self.faceup),
                 "deck_count": len(self.deck),
                 "discard_count": len(self.discard),
                 "claims": list(self.claims),
                 "players": players,
                 "scores": self.scores}
        if self.expecting:
            state["expecting"] = self.expecting
        return state

    def _ticket_view(self, player, ticket):
        return dict(ticket, completed=self._connected(player, *ticket["cities"]))

    def private_state(self, player):
        info = player.public()
        info["hand"] = list(player.hand)
        info["tickets"] = [self._ticket_view(player, t) for t in player.tickets]
        if player.pending_offer is not None:
            info["pending_offer"] = list(player.pending_offer)
        return info

    def log_since(self, seq=0):
        return [event for event in self.log if event["seq"] > seq]
