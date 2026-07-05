# TBT Game Server API

A RESTful API for playing a game (per `../rules.md`) on any TBT map
(per `map.schema.json`). It is the contract between the game server (component 5
of the README design) and its consumers: human clients (6) and robots (7). Both
kinds of client use exactly the same API.

This document specifies v1, which covers the core mechanics of `rules.md`
(drawing cards, claiming routes, destination tickets, scoring, game end).
Tunnels and ferries are reserved as future extensions (see the end of this
document). The machine-readable version of this spec is `api.openapi.yaml`.

## Principles

- **Server-authoritative.** The server is the rules engine. Clients submit
  intended actions; the server validates them against `rules.md` and rejects
  illegal ones. Clients never need to compute legality (though smart bots may
  want to, to plan ahead).
- **Hidden information via tokens.** Joining a game yields a secret bearer
  token. Hands and kept tickets are only visible through the token-guarded
  private player view; everything else is public.
- **Polling.** Public game state carries a monotonically increasing
  `state_version`. Clients poll `GET /games/{g}` and act when it changes; the
  server supports `ETag`/`If-None-Match` on this resource (the `ETag` is the
  `state_version`) so polling is cheap. Push (webhooks/SSE) is a future
  extension.
- **Storage is an implementation detail.** The API exposes no database
  concepts; the server may keep games in memory, JSON files, or a DB.

## The map and identifiers

A game is created from a TBT map JSON document exactly as produced by
`tbt-edit` (schema: `map.schema.json`). The server uses its `cities`, `routes`
(with `length` and `tracks`), and `tickets`; `geometry` and any graphic info
are passed through untouched for clients that render the board.

The map schema has no explicit IDs, so the API derives stable ones:

- **City**: its name, e.g. `Scranton`.
- **Route**: the two city names sorted lexicographically and joined with `|`,
  e.g. `NYC|Philadelphia`. (City pairs uniquely identify a route in the TBT
  data model.)
- **Track lane**: 0-based index into the route's `tracks` array.
- **Ticket**: a server-assigned integer `ticket_id`, stable for the life of
  the game.

The same route/city ID scheme is intended for SVG metadata (issue #26), so a
rendered board and the API agree on names.

Maps must be playable: every route needs a `length` and at least one entry in
`tracks`, and v1 rejects maps at game creation if these are missing. A lane
color of `random` is resolved to a concrete color by the server at game
creation (mirroring `tbt-edit colors`); `blank` lanes are claimable with any
single color per `rules.md`.

## Resources

| Method & path | Auth | Purpose |
|---|---|---|
| `POST /games` | — | Create a game from a map JSON |
| `GET /games/{g}` | — | Public game state (poll this) |
| `GET /games/{g}/map` | — | The map the game is played on |
| `POST /games/{g}/players` | — | Join; returns `player_id` + token |
| `GET /games/{g}/players/{p}` | token | Private view: hand, tickets, offers |
| `POST /games/{g}/start` | token | Begin play once everyone has joined |
| `POST /games/{g}/card-draws` | token | Turn action: draw a train card |
| `POST /games/{g}/claims` | token | Turn action: claim a route lane |
| `POST /games/{g}/ticket-draws` | token | Turn action: request a ticket offer |
| `POST /games/{g}/ticket-keeps` | token | Resolve a pending ticket offer |
| `GET /games/{g}/log` | — | Ordered public event log |

### Creating and joining

`POST /games` takes the map inline plus optional `options` overriding the
defaults implied by `rules.md`:

```json
{
  "map": { "cities": {...}, "routes": [...], "tickets": [...] },
  "options": {
    "starting_cars": 45,
    "starting_hand": 4,
    "faceup_count": 5,
    "ticket_offer": 3,
    "ticket_keep_min": 1,
    "setup_ticket_keep_min": 1,
    "last_round_cars": 2,
    "parallel_min_players": 4
  }
}
```

It returns a `game_id`. Each `POST /games/{g}/players` (body: `{"name": ...,
"kind": "human" | "bot"}`) returns a `player_id` and a secret `token`; the
token is shown once and authenticates all later private/action calls as an
HTTP bearer token. Join order is turn order.

Any joined player may `POST /games/{g}/start` once at least two players have
joined. Starting deals each player `starting_hand` train cards and a setup
ticket offer of `ticket_offer` tickets, and reveals `faceup_count` face-up
cards. The game stays in the `setup` phase until every player resolves their
setup offer with `POST /ticket-keeps` (keeping at least
`setup_ticket_keep_min`); then the first player's turn begins.

### Public state — `GET /games/{g}`

```json
{
  "game_id": "…",
  "state_version": 41,
  "phase": "setup | active | last_round | finished",
  "current_player": "p2",
  "expecting": "turn | second_card | ticket_keep | setup_ticket_keeps",
  "faceup": ["red", "wild", "blue", "blue", "green"],
  "deck_count": 62,
  "discard_count": 18,
  "claims": [ {"route": "NYC|Philadelphia", "track": 1, "player": "p1"} ],
  "players": [
    {
      "player_id": "p1", "name": "Ada", "kind": "bot",
      "cars": 31, "hand_count": 7, "ticket_count": 3, "claimed_routes": 4
    }
  ],
  "scores": null
}
```

`expecting` tells clients (especially bots) what input the game is waiting
for: a fresh turn action, the current player's second card draw, the current
player's ticket keep, or (during setup) outstanding setup keeps. When `phase`
is `finished`, `scores` holds the final per-player breakdown: route points,
ticket points gained and lost, longest-path bonus, and total.

### Private state — `GET /games/{g}/players/{p}`

Requires the bearer token for player `p` (anyone else gets `403`). Adds to the
public player info: `hand` (list of card colors), `tickets` (each with
`ticket_id`, `cities`, `points`, and a live `completed` boolean computed over
the player's claims), and `pending_offer` (the tickets currently offered, if
any).

### Turn actions

All action posts require a token and are validated in this order:

1. `401` — missing/invalid token.
2. `409` — it isn't this player's turn, the game isn't in a phase where this
   action is allowed, or a different follow-up is `expecting`-ed.
3. `422` — the action is yours to take but illegal (bad color set, lane
   already claimed, not enough cars, …). The body's `error` field carries a
   machine-readable code, e.g. `{"error": "lane_claimed", "message": "…"}`.

**Draw a train card** — `POST /games/{g}/card-draws` with
`{"source": "deck"}` or `{"source": "faceup", "card": "blue"}`. The response
reports the card received and `draws_remaining` for this turn. Per `rules.md`
a turn is two draws, except taking a face-up wild is the whole turn (and a
face-up wild is `422 wild_needs_full_draw` as a second draw). Face-up gaps are
refilled from the deck immediately; the discard pile is reshuffled into the
deck when the deck empties.

**Claim a route lane** — `POST /games/{g}/claims` with

```json
{ "route": "NYC|Philadelphia", "track": 0, "cards": ["blue", "blue", "wild"] }
```

`cards` come from the player's hand, must number exactly the route's
`length`, and must be one color (plus any number of wilds) matching the lane's
color — any one color for a `blank` lane. The server also enforces the
parallel-track rule: with fewer than `parallel_min_players` players, once any
lane of a route is claimed the rest of that route is closed. On success the
player's cars decrease by `length`, the route points (per the `rules.md`
table) are banked, and if the player ends the turn with `last_round_cars` or
fewer cars the game enters `last_round`.

**Destination tickets** — `POST /games/{g}/ticket-draws` (empty body) deals
`ticket_offer` tickets from the ticket deck into `pending_offer` and the turn
waits (`expecting: ticket_keep`). The player then posts
`POST /games/{g}/ticket-keeps` with `{"tickets": [<ticket_id>, …]}`, keeping
at least `ticket_keep_min`; unkept tickets go to the bottom of the ticket
deck. The same endpoint resolves setup offers.

### Game end

After the `last_round` trigger, every other player takes exactly one more
turn. The server then scores everything per `rules.md` — claimed routes,
each ticket's `points` added if its cities are connected through the owner's
claims and subtracted if not, and the +10 longest-path bonus — sets `phase`
to `finished`, populates `scores`, and reveals all hands and tickets in the
public state.

### The log — `GET /games/{g}/log`

An append-only list of public events, each with a `seq` number, so bots and
replayers get one ordered history instead of merging the action collections:

```json
[
  {"seq": 12, "player": "p1", "type": "card_draw", "source": "faceup", "card": "red"},
  {"seq": 13, "player": "p1", "type": "card_draw", "source": "deck"},
  {"seq": 14, "player": "p2", "type": "claim", "route": "NYC|Philadelphia", "track": 0, "cards": ["blue","blue","wild"]},
  {"seq": 15, "player": "p1", "type": "ticket_draw", "offered": 3},
  {"seq": 16, "player": "p1", "type": "ticket_keep", "kept": 2}
]
```

Hidden information stays hidden: deck draws omit the card, ticket events show
only counts. Claims reveal the cards spent, as at a table. `?since=<seq>`
returns only newer events.

## Future extensions (reserved, not in v1)

- **Tunnels and ferries** — the claim flow in `rules.md` needs extra steps
  (tunnel reveal/pay-or-forfeit, ferry wild minimums), and the map schema
  needs a way to mark a route as a tunnel/ferry first (schema follow-up).
  `claims` responses reserve a `resolution` field for the tunnel reveal.
- **Push notifications** — SSE or webhooks as an alternative to polling.
- **Spectators** — read-only tokens for watching without a seat.
- **Persistence / lobbies** — listing open games (`GET /games`), reconnecting
  by token is already implicit, but durable storage and matchmaking are out
  of scope for v1.
