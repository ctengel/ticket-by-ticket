"""Tunable strategy weights and the difficulty presets built from them"""

from dataclasses import dataclass


@dataclass
class Knobs:
    """Weights the heuristic brain steers by; all map-agnostic

    skill: 0..1, lower adds score noise and outright blunders
    ticket_affinity: weight of ticket completion vs raw route points
    long_route_bonus: extra preference for long routes
    build_speed: 0 hoards cards, 1 claims as soon as affordable
    wild_frugality: penalty per wild spent when color cards would do
    keep_greed: 0..1, higher keeps more of a ticket offer
    """

    skill: float = 1.0
    ticket_affinity: float = 1.0
    long_route_bonus: float = 0.5
    build_speed: float = 0.5
    wild_frugality: float = 0.7
    keep_greed: float = 0.5


PRESETS = {
    "easy": Knobs(skill=0.35, ticket_affinity=0.5, build_speed=0.8),
    "normal": Knobs(skill=0.8),
    "hard": Knobs(),
}
