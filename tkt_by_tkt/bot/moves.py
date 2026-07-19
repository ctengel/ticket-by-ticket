"""Move and Decision types produced by a Brain and consumed everywhere

A Move maps one-to-one onto a turn-action endpoint; a Decision wraps the
chosen move with the brain's rationale so the runner's log and the
advisor's recommendation read the same.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class DrawCard:
    source: str                  # "deck" | "faceup"
    card: Optional[str] = None   # required when source == "faceup"


@dataclass(frozen=True)
class ClaimRoute:
    route: str                   # api route id: sorted cities joined with |
    track: int
    cards: Tuple[str, ...]


@dataclass(frozen=True)
class DrawTickets:
    pass


@dataclass(frozen=True)
class KeepTickets:
    tickets: Tuple[int, ...]


@dataclass
class Decision:
    move: object
    rationale: str
    score: float = 0.0
    # runners-up as (move, score, why) for advisor output
    alternatives: List[Tuple[object, float, str]] = field(default_factory=list)


def format_cards(cards):
    """Compact hand summary like 'blue x2 + wild'"""
    counted = Counter(cards)
    parts = []
    for color in sorted(counted, key=lambda c: (c == "wild", c)):
        count = counted[color]
        parts.append(color if count == 1 else "%s x%d" % (color, count))
    return " + ".join(parts)


def describe(move):
    """One-line human description of a move"""
    if isinstance(move, DrawCard):
        if move.source == "deck":
            return "draw a card from the deck"
        return "draw the face-up %s" % move.card
    if isinstance(move, ClaimRoute):
        return "claim %s track %d with %s" % (move.route, move.track,
                                              format_cards(move.cards))
    if isinstance(move, DrawTickets):
        return "draw destination tickets"
    if isinstance(move, KeepTickets):
        return "keep ticket(s) %s" % ", ".join(str(t) for t in move.tickets)
    return str(move)


def move_dict(move):
    """Machine-readable form for --json advisor output"""
    if isinstance(move, DrawCard):
        body = {"action": "card_draw", "source": move.source}
        if move.card is not None:
            body["card"] = move.card
        return body
    if isinstance(move, ClaimRoute):
        return {"action": "claim", "route": move.route, "track": move.track,
                "cards": list(move.cards)}
    if isinstance(move, DrawTickets):
        return {"action": "ticket_draw"}
    if isinstance(move, KeepTickets):
        return {"action": "ticket_keep", "tickets": list(move.tickets)}
    raise ValueError("unknown move %r" % (move,))
