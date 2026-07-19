# TBT Rules

Core mechanics for playing a game on a TBT map. These rules are independent of any
particular map — they apply to whatever `cities`, `routes`, and `tickets` your map
JSON defines.

## Overview

Players compete to build the biggest rail network. On a turn you either collect
train cards, claim a route between two cities, or draw destination tickets. At the
end of the game, points come from routes claimed, destination tickets completed (or
missed), and the longest unbroken chain of routes.

## Components

- **Train cars**: each player starts with a fixed personal supply (classically 45).
  Claiming a route spends cars from this supply.
- **Train cards**: colored cards matching the color options used on the map's
  route `tracks` (plus a wild/locomotive color that matches anything).
- **Destination tickets**: cards naming a pair of `cities` and a `points` value,
  drawn from the map's `tickets`.
- **The map**: `cities` and the `routes` connecting them, each route having a
  `length` (cars required to claim it) and one or more `tracks` (parallel,
  independently-claimable lanes, each with its own color).

## Setup

1. Deal each player a starting hand of train cards.
2. Deal each player some destination tickets; each player must keep at least one.
3. Pick a starting player.

## Turn actions

Each turn, a player takes exactly one of the following:

- **Draw train cards** — take two cards from the draw pile and/or face-up display;
  a face-up wild card counts as your whole draw for the turn. If three or more of
  the face-up cards are ever wild, the entire face-up display is discarded and
  replaced from the draw pile (repeated as needed).
- **Claim a route** — discard train cards matching one `tracks` lane's color and
  count equal to the route's `length`, then place that many cars from your supply
  on the route.
- **Draw destination tickets** — draw new ticket cards and keep at least one.

## Claiming a route

- **Standard**: discard cards of the lane's color equal to the route `length`.
  A "blank"/wild lane can be claimed with any single color.
- **Tunnel routes**: after discarding, reveal the top three cards of the draw
  pile. For each revealed card that matches the lane's color, discard one more
  card of that color. If you can't cover the extra cost, the claim fails and the
  cards you already discarded are lost.
- **Ferry routes**: claiming requires a minimum number of wild/locomotive cards
  as part of the discard.
- **Parallel tracks**: a route with more than one `tracks` entry has that many
  independent lanes — different players may claim different lanes on the same
  route, but a single player may claim at most one lane of any given route. With
  few players, only one lane per route may be claimed at all.
- A route (or a specific lane, for multi-track routes) can only be claimed once.

## Scoring

**Route points**, by `length`:

| length | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| points | 1 | 2 | 4 | 7 | 10 | 15 |

**Destination tickets**: at game end, a ticket's `points` are added to your score
if its two `cities` are connected through routes you claimed, and subtracted if
not.

**Longest path bonus**: whoever has the longest unbroken chain of their own
claimed routes gets a flat +10 point bonus.

## Game end

The game enters its final round as soon as a player ends their turn with two or
fewer cars left in their supply. Every other player then takes exactly one more
turn, after which all scoring is tallied and the highest total wins.
