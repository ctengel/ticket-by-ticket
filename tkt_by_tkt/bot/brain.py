"""Brain: turns a GameView into a Decision

HeuristicBrain is deterministic (given a seeded rng) and map-agnostic:
it plans cheapest paths for its tickets, claims target routes when
affordable, and otherwise collects the cards those routes need. Knobs
shift the weights; skill below 1.0 injects noise and occasional
blunders. Any other strategy (including a learned one) just implements
Brain.decide.
"""

import heapq
from abc import ABC, abstractmethod

from .knobs import Knobs
from .moves import ClaimRoute, Decision, DrawCard, DrawTickets, KeepTickets
from .view import BLANK, WILD, claim_combos, route_points_for

# Below this many cars the brain plays like the last round has begun
ENDGAME_CARS = 6
# Cars to hold in reserve before considering new tickets worthwhile
TICKET_DRAW_MIN_CARS = 12


class Brain(ABC):
    """Strategy interface: one decision per game state"""

    @abstractmethod
    def decide(self, view, rng):
        """Return a Decision for the move the game currently awaits"""


class HeuristicBrain(Brain):

    def __init__(self, knobs=None):
        self.knobs = knobs or Knobs()

    def decide(self, view, rng):
        if view.pending_offer is not None:
            return self._decide_keep(view, rng)
        if view.expecting == "second_card":
            return self._decide_second_card(view)
        return self._decide_turn(view, rng)

    # ----- planning ----------------------------------------------------

    def _adjacency(self, view, discount=None):
        """City graph of routes still usable by me; my routes cost 0

        Routes in discount (the current plan) are near-free so new
        tickets that overlap the existing plan look cheap.
        """
        adjacency = {}
        for rid, route in view.routes.items():
            if rid in view.my_claims:
                cost = 0.0
            elif view.free_lanes(rid):
                cost = float(route["length"])
                if discount and rid in discount:
                    cost *= 0.3
                cost = max(0.1, cost * (1.0 - 0.1 * self.knobs.long_route_bonus))
            else:
                continue  # closed to me
            one, two = route["cities"]
            adjacency.setdefault(one, []).append((two, rid, cost))
            adjacency.setdefault(two, []).append((one, rid, cost))
        return adjacency

    @staticmethod
    def _dijkstra(adjacency, source, goal):
        """(cost, [rids on the cheapest path]) or None if unreachable"""
        heap = [(0.0, source)]
        dist = {source: 0.0}
        prev = {}
        done = set()
        while heap:
            cost, city = heapq.heappop(heap)
            if city in done:
                continue
            done.add(city)
            if city == goal:
                path = []
                while city != source:
                    city, rid = prev[city]
                    path.append(rid)
                return cost, path
            for other, rid, step in adjacency.get(city, ()):
                candidate = cost + step
                if candidate < dist.get(other, float("inf")):
                    dist[other] = candidate
                    prev[other] = (city, rid)
                    heapq.heappush(heap, (candidate, other))
        return None

    def _plan(self, view):
        """Target routes for my incomplete tickets

        Returns ({rid: ticket points routed through it}, [dead tickets]),
        where dead tickets can no longer be connected.
        """
        adjacency = self._adjacency(view)
        targets = {}
        dead = []
        for ticket in view.tickets:
            if ticket.completed:
                continue
            found = self._dijkstra(adjacency, ticket.cities[0],
                                   ticket.cities[1])
            if found is None:
                dead.append(ticket)
                continue
            for rid in found[1]:
                if rid not in view.my_claims:
                    targets[rid] = targets.get(rid, 0.0) + ticket.points
        return targets, dead

    def _color_deficits(self, view, targets):
        """Cards still missing per color to afford the target lanes"""
        deficits = {}
        for rid in targets:
            route = view.routes[rid]
            lanes = view.free_lanes(rid)
            if not lanes:
                continue
            for color in {route["tracks"][t] for t in lanes}:
                if color == BLANK:
                    held = [c for c in view.hand
                            if c != WILD and view.hand[c] > 0]
                    if not held:
                        continue  # any color works; the deck will do
                    color = max(held, key=lambda c: view.hand[c])
                need = route["length"] - view.hand[color]
                if need > 0:
                    deficits[color] = deficits.get(color, 0) + need
        return deficits

    # ----- the main turn -----------------------------------------------

    def _decide_turn(self, view, rng):
        knobs = self.knobs
        targets, dead = self._plan(view)
        endgame = view.phase == "last_round" or view.cars <= ENDGAME_CARS
        candidates = []  # (score, move, why)

        for rid, route in view.routes.items():
            length = route["length"]
            if view.cars < length:
                continue
            for track in view.free_lanes(rid):
                for cards in claim_combos(view.hand, route["tracks"][track],
                                          length):
                    wilds = cards.count(WILD)
                    points = route_points_for(length)
                    at_stake = targets.get(rid, 0.0)
                    if endgame:
                        # every remaining turn is precious: bank the
                        # biggest claim we can still afford
                        score = (50.0 + points
                                 + knobs.ticket_affinity * at_stake
                                 - 0.1 * wilds)
                    else:
                        score = (points
                                 + knobs.ticket_affinity * at_stake
                                 + knobs.long_route_bonus * length
                                 - knobs.wild_frugality * wilds)
                        if targets and rid not in targets:
                            # off-plan claims burn cards the plan needs
                            score -= 1.5 * knobs.ticket_affinity
                    why = "%d route pts" % points
                    if at_stake:
                        why += ", on a ticket path (%g pts at stake)" % at_stake
                    if wilds:
                        why += ", spends %d wild(s)" % wilds
                    candidates.append(
                        (score, ClaimRoute(rid, track, tuple(cards)), why))

        # with no ticket plan, collect toward any still-open route
        deficits = self._color_deficits(view, targets or view.routes)
        pool = view.deck_count + view.discard_count
        draw_base = 3.0 + 2.0 * (1.0 - knobs.build_speed)
        if pool > 0:
            candidates.append((draw_base, DrawCard("deck"),
                               "build up the hand"))
        for color in dict.fromkeys(view.faceup):
            need = deficits.get(color, 0)
            if color == WILD:
                if deficits and max(deficits.values()) >= 2:
                    candidates.append(
                        (draw_base + 1.0, DrawCard("faceup", WILD),
                         "a wild is worth the whole turn while still short"))
            elif need > 0:
                candidates.append(
                    (draw_base + 1.5 + 0.2 * need, DrawCard("faceup", color),
                     "face-up %s fills a need (%d more wanted)"
                     % (color, need)))
            elif pool == 0:
                candidates.append((draw_base * 0.5, DrawCard("faceup", color),
                                   "deck is empty; take what's showing"))

        incomplete = [t for t in view.tickets if not t.completed
                      and t not in dead]
        if (view.phase == "active" and not incomplete
                and view.cars >= TICKET_DRAW_MIN_CARS):
            candidates.append(
                (2.0 + 4.0 * knobs.ticket_affinity, DrawTickets(),
                 "no open tickets and plenty of cars: draw new goals"))

        if not candidates:
            # nothing looks legal; the runner's fallback ladder will cope
            candidates.append((0.0, DrawCard("deck"), "no better option"))

        decision = self._pick(candidates, rng)
        if dead:
            decision.rationale += "; writing off unreachable %s" % ", ".join(
                "%s-%s" % t.cities for t in dead)
        return decision

    def _decide_second_card(self, view):
        """Finish a two-card draw; a face-up wild is never legal here"""
        targets, _ = self._plan(view)
        deficits = self._color_deficits(view, targets or view.routes)
        needed = [c for c in dict.fromkeys(view.faceup)
                  if c != WILD and deficits.get(c, 0) > 0]
        if needed:
            color = max(needed, key=lambda c: deficits[c])
            return Decision(DrawCard("faceup", color),
                            "second draw: face-up %s is still needed" % color)
        if view.deck_count + view.discard_count > 0:
            return Decision(DrawCard("deck"),
                            "second draw: nothing useful showing")
        color = next((c for c in view.faceup if c != WILD), None)
        if color is not None:
            return Decision(DrawCard("faceup", color),
                            "second draw: deck is empty")
        return Decision(DrawCard("deck"), "second draw: no cards anywhere")

    # ----- ticket offers -----------------------------------------------

    def _decide_keep(self, view, rng):
        """Choose which of the offered tickets to keep (setup or turn)"""
        knobs = self.knobs
        targets, _ = self._plan(view)
        adjacency = self._adjacency(view, discount=targets)
        threshold = 2.0 * (1.0 - knobs.keep_greed)
        sigma = (1.0 - knobs.skill) * 3.0
        scored = []
        for ticket in view.pending_offer:
            found = self._dijkstra(adjacency, ticket.cities[0],
                                   ticket.cities[1])
            if found is None:
                net = float("-inf")
                why = "%s-%s (%g pts): unreachable" % (
                    ticket.cities[0], ticket.cities[1], ticket.points)
            else:
                net = knobs.ticket_affinity * ticket.points - found[0]
                why = "%s-%s (%g pts, ~%.1f to build)" % (
                    ticket.cities[0], ticket.cities[1], ticket.points,
                    found[0])
            if sigma:
                net += rng.gauss(0.0, sigma)
            scored.append((net, ticket, why))
        keep = [(net, t, why) for net, t, why in scored if net > threshold]
        if not keep:
            keep = [max(scored, key=lambda item: item[0])]
        kept_ids = tuple(sorted(t.ticket_id for _, t, _ in keep))
        rationale = "keep " + "; ".join(why for _, _, why in keep)
        dropped = [why for net, t, why in scored
                   if t.ticket_id not in kept_ids]
        if dropped:
            rationale += " | return " + "; ".join(dropped)
        return Decision(KeepTickets(kept_ids), rationale,
                        score=sum(net for net, _, _ in keep))

    # ----- selection ----------------------------------------------------

    def _pick(self, candidates, rng):
        """Best-scoring move, degraded by the skill knob"""
        skill = self.knobs.skill
        sigma = (1.0 - skill) * 3.0
        noisy = [(score + (rng.gauss(0.0, sigma) if sigma else 0.0),
                  move, why) for score, move, why in candidates]
        noisy.sort(key=lambda item: item[0], reverse=True)
        choice = noisy[0]
        if len(noisy) > 1 and rng.random() < (1.0 - skill) * 0.5:
            choice = noisy[rng.randrange(len(noisy))]  # a blunder
        alternatives = [(move, score, why) for score, move, why in noisy
                        if move is not choice[1]][:2]
        return Decision(choice[1], choice[2], score=choice[0],
                        alternatives=alternatives)
