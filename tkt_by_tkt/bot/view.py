"""GameView: one merged, normalized snapshot for the brain to reason over

Combines the public state, the player's private view, and the map into a
single object, and re-implements the few bits of rules.md math a client
needs to judge legality locally: open lanes, claimable card combos, and
route point values. The server stays authoritative -- these mirrors only
guide the bot's choices -- and because the API exposes no game options,
the default option values are assumed here.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

WILD = "wild"
BLANK = "blank"

# Assumed defaults; the API does not expose a game's options
DEFAULT_ROUTE_POINTS = [1, 2, 4, 7, 10, 15]
ROUTE_POINTS_STEP = 5
PARALLEL_MIN_PLAYERS = 4


def route_id(city_a, city_b):
    """Stable route ID per api.md: sorted city names joined with |"""
    return "|".join(sorted([city_a, city_b]))


def route_points_for(length):
    """Points for a claimed route, extrapolating past the default table"""
    table = DEFAULT_ROUTE_POINTS
    if length <= len(table):
        return table[length - 1]
    return table[-1] + ROUTE_POINTS_STEP * (length - len(table))


def claim_combos(hand, lane_color, length):
    """Card combos (one color plus wilds) that could claim a lane

    Returns the minimum-wild combo per usable color, plus the all-wild
    combo when possible; a blank lane accepts any single color.
    """
    wilds = hand[WILD]
    if lane_color == BLANK:
        colors = [c for c in hand if c != WILD and hand[c] > 0]
    else:
        colors = [lane_color]
    combos = []
    for color in colors:
        need_wild = max(0, length - hand[color])
        if length - need_wild > 0 and need_wild <= wilds:
            combos.append([color] * (length - need_wild)
                          + [WILD] * need_wild)
    if wilds >= length:
        combos.append([WILD] * length)
    return combos


@dataclass
class Ticket:
    ticket_id: int
    cities: Tuple[str, str]
    points: float
    completed: bool = False


@dataclass
class GameView:
    my_id: str
    phase: str                        # setup | active | last_round | finished
    expecting: Optional[str]
    current_player: Optional[str]
    state_version: int
    faceup: List[str]
    deck_count: int
    discard_count: int
    hand: Counter
    cars: int
    tickets: List[Ticket]             # kept tickets
    pending_offer: Optional[List[Ticket]]
    players: List[dict]               # public player rows
    routes: Dict[str, dict]           # rid -> map route dict
    lane_owner: Dict[Tuple[str, int], str]
    my_claims: Set[str]               # rids where I own a lane
    # lanes the server rejected this cycle (runner 422 fixups)
    blacklist: Set[Tuple[str, int]] = field(default_factory=set)

    @classmethod
    def build(cls, public, private, map_dict, my_id):
        routes = {route_id(*r["cities"]): r for r in map_dict["routes"]}
        lane_owner = {(c["route"], c["track"]): c["player"]
                      for c in public["claims"]}
        my_claims = {rid for (rid, _), pid in lane_owner.items()
                     if pid == my_id}
        tickets = [Ticket(t["ticket_id"], tuple(t["cities"]), t["points"],
                          t.get("completed", False))
                   for t in private.get("tickets", [])]
        offer = private.get("pending_offer")
        if offer is not None:
            offer = [Ticket(t["ticket_id"], tuple(t["cities"]), t["points"])
                     for t in offer]
        return cls(my_id=my_id,
                   phase=public["phase"],
                   expecting=public.get("expecting"),
                   current_player=public.get("current_player"),
                   state_version=public["state_version"],
                   faceup=list(public["faceup"]),
                   deck_count=public["deck_count"],
                   discard_count=public["discard_count"],
                   hand=Counter(private.get("hand", [])),
                   cars=private["cars"],
                   tickets=tickets,
                   pending_offer=offer,
                   players=list(public["players"]),
                   routes=routes,
                   lane_owner=lane_owner,
                   my_claims=my_claims)

    def is_my_move(self):
        """Does the game await input from this player right now?"""
        if self.phase == "setup":
            return self.pending_offer is not None
        return (self.current_player == self.my_id
                and self.expecting in ("turn", "second_card", "ticket_keep"))

    def free_lanes(self, rid):
        """Track indexes on rid still claimable by me (rules.md lanes)"""
        if rid in self.my_claims:
            return []
        tracks = range(len(self.routes[rid]["tracks"]))
        taken = any((rid, t) in self.lane_owner for t in tracks)
        if taken and len(self.players) < PARALLEL_MIN_PLAYERS:
            return []  # parallel lanes closed at small player counts
        return [t for t in tracks
                if (rid, t) not in self.lane_owner
                and (rid, t) not in self.blacklist]
