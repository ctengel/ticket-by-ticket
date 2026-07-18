# TBT bot design

The bot (`tkt_by_tkt/bot/`, console script `tbt-bot`) plays a game through
the server API (`design/api.md`) — it never imports the rules engine. One
decision core serves two modes:

- **auto**: join a game (`POST /players`, `kind=bot`), poll the public
  state, and whenever the game awaits this player, decide *and execute*
  the move, until the game finishes. The bot never creates or starts
  games; a human (or any client) POSTs `/start`, and the bot resolves
  its own setup ticket offer once one is dealt.
- **advise**: a human shares their player id and bearer token; the bot
  fetches the same state, runs the same brain, and prints the move it
  *would* make — with a rationale and the runners-up — without making it.

## Module layout

| module | responsibility |
|---|---|
| `client.py` | thin HTTP client; injectable requests-style session (tests pass a fastapi `TestClient`) |
| `view.py` | `GameView`: public state + private view + map merged; local legality math (`free_lanes`, `claim_combos`, `route_points_for`) |
| `moves.py` | `DrawCard` / `ClaimRoute` / `DrawTickets` / `KeepTickets`, and `Decision` = move + rationale + alternatives |
| `knobs.py` | `Knobs` weights + `easy`/`normal`/`hard` presets |
| `brain.py` | `Brain` ABC and `HeuristicBrain` |
| `runner.py` | auto loop: ETag poll, decide, execute, recover |
| `advisor.py` | one-shot / `--watch` recommendation rendering (text or `--json`) |
| `cli.py` | `tbt-bot auto` / `tbt-bot advise` |

## The heuristic brain

Deterministic given a seeded RNG, and map-agnostic. Per decision:

1. **Plan**: build a city graph of routes still usable (own routes cost 0,
   routes with no lane open to this player removed, others cost their
   length, slightly discounted by `long_route_bonus`). Dijkstra per
   incomplete ticket; the union of on-path unclaimed routes is the target
   set, each accumulating the ticket points that ride on it. Unreachable
   tickets are written off.
2. **Score candidates**: every affordable claim (per open lane, per card
   combo from `claim_combos`) scored by route points + `ticket_affinity` ×
   points-at-stake + `long_route_bonus` − `wild_frugality` × wilds spent;
   drawing scored from color deficits on target lanes (face-up needed
   colors beat the deck; a face-up wild only when 2+ cards short, since it
   costs the whole turn; with no ticket plan, deficits fall back to all
   open routes); a ticket draw only when all kept tickets are complete and
   cars are plentiful. In the last round (or at ≤6 cars) claims dominate
   and the biggest affordable one wins.
3. **Skill**: `skill < 1` adds Gaussian noise to every score and a blunder
   probability of picking a random legal candidate — the difficulty dial.

Ticket offers (setup and mid-game) are kept when `ticket_affinity` ×
points − estimated build cost clears a `keep_greed` threshold, with routes
already in the plan discounted; at least one is always kept.

A future ML strategy just implements `Brain.decide(view, rng)`.

## Runner realities

The API does not expose a game's options, so the bot assumes the defaults
(route point table, `parallel_min_players` 4, keep minimums 1) and treats
the server as authoritative when they differ:

- **409** (someone moved first, or a duplicate request): drop the cached
  ETag and re-poll.
- **422** on a claim (`lane_claimed`/`route_closed`/`one_lane_per_route`):
  blacklist the lane in the view, re-decide once.
- **422** `keep_too_few`: keep one more ticket from the offer.
- Anything else: a fallback ladder — deck draw, each face-up non-wild,
  face-up wild, ticket draw. If every rung is rejected the runner exits
  nonzero (`BotStuck`): the engine currently has no legal move to offer
  when card and ticket sources are exhausted and no claim is affordable,
  which small maps can reach.
- Connection errors back off exponentially (1s → 30s); a 404 (server
  restarted, games are in memory) exits cleanly.

Polling uses `If-None-Match` with the state ETag, so idle polls are 304s.
