# ticket-by-ticket
Tools to easily create maps and play a popular game

The purpose is to make custom map generation based on real world geography easy and fun!  The MVP is to be able to generate a board and optionally destination tickets.  From there we want to either design a RESTful API based game engine or find a way to import our custom maps to another game.

The name is a play on words of direct translations of the original. Fahrkarte fuer Fahrkarte was a close second.

## Design

![Design diagram](/design/tbt-design.png)

TBT will consist of the following components/flows:

1. We rely on outside data sources
   - Existing / legacy / planned railroads
   - Actual city and station info
   - Raster graphics of geography, regions, etc
   - Note in future could be a nonexistant/fantasy/elaborated place
   - These outputs go to 2, 4, and 6
2. Map designer
   - Has 1 available
   - Decides where to put actual points/routes data (could be traced over raster or pulled from points) - this becomes 3
   - optionally manipulates map output from 4 to improve
3. points/routes data
   - in JSON
   - from a person 2
   - converts to a map 4
   - also loads to DB 5
4. map generator
   - reads 1 raster and 3 data
   - outputs a single file
   - may also be used by PC game 6
   - may be edited by person 2
   - optionally, prints destination tickets also
5. database / API
   - inputs map data 3
   - interacts with client 6 and robot 7
   - stores game state
6. client
   - uses map data 3
   - interacts with db 5
   - may use 4 map or 1 map
7. robot
   - interacts with db 5
   - may get map data 3

## Get started

1. Draw a map in Google maps
   - Just put points with simple names for cities/stations
   - example https://www.google.com/maps/d/edit?mid=1hx0aYHMCiwSoYo_vl30oC0rnj-tKL-K5&usp=sharing
2. Export the layer as CSV
   - Example output `sample.csv`
   - Needs to have columns `WKT`, `name`
   - `WKT` is format `POINT (lat lng)`
   - `name` is simply the name of the city
3. Convert CSV to JSON
   - `tbd-edit import`
   - It figures out geometry automatically
4. Design routes/tracks
   - `tbt-edit con`
   - one can continually run 6 to check work visually
5. Design destination tickets
6. Generate map
   - `tbt-edit export -i map.svg`
   - Input JSON file generated in 3 and modified in 4
   - select a map source if desired (example http://maps.stamen.com/ )
   - It will auto download background raster
   - It will generate SVG from JSON, which references the raster as a layer
   - Output will be an SVG and a png

## JSON spec

Map:

- geometry
  - real: lat1 (NW), long1 (NW), lat3 (SE) lat4 (SE)
  - resolution: x, y
  - image: relative filename
- cities
  - name: x, y
- route: (list)
  - cities: 1, 2
  - len: int
  - tracks:
    - color
    - color
    - auto
- tickets (list)
  - cities: 1, 2
  - points: int

(see `map.schema.json`)

## Rules

See `rules.md` for core game mechanics.

## Game server API

See `design/api.md` for the RESTful game server API used by human and bot
clients (machine-readable spec: `design/api.openapi.yaml`).

To run the server (implemented with FastAPI, kept as an optional extra so the
map-editing tools stay dependency-free):

```
pip install -e .[server]
tbt-server [--host 127.0.0.1] [--port 8080]
```

Then create a game from any TBT map JSON, e.g.:

```
curl -s -X POST localhost:8080/v1/games \
     -H 'Content-Type: application/json' \
     -d "{\"map\": $(cat maps/nyc287.json)}"
```

## Web UI

The server also serves a browser client (component 6 in the design diagram)
for humans: run `tbt-server` and open `http://127.0.0.1:8080/`. It plays one
seat in an existing game — create the game and join players with the API as
above, then enter the game ID, player ID, and token from those calls (or open
a prefilled link, `/ui/?game=G&player=P&token=T`). The board is drawn over
OSM slippy-map tiles (`https://tile.openstreetmap.org` by default; any
`{z}/{x}/{y}` tile URL template can be substituted on the join form). Click a
face-up card or the deck to draw, click a route's lane on the board to claim
it, and resolve destination-ticket offers from the sidebar; the server
remains the rules engine, so illegal moves just come back as error banners.
The UI can point at another tbt-server by filling in the server URL field
(the API allows cross-origin requests).

## Bot

The bot (component 7 in the design diagram) plays a game over the server API,
either on its own or as an advisor to a human player. It is a pure API client
(`design/bot.md` describes the internals) with two modes:

```
pip install -e .[bot]

# full auto: join the game and play it to the end (someone else starts it)
tbt-bot auto --server http://localhost:8080 --game GAMEID [--name "TBT Bot"]

# advisor: recommend a move for your own seat without making it
tbt-bot advise --server http://localhost:8080 --game GAMEID \
        --player p1 --token YOURTOKEN [--json] [--watch]
```

Strategy is a deterministic heuristic with tunable knobs. `--profile
easy|normal|hard` picks a preset; individual knobs override it: `--skill`
(lower adds mistakes), `--ticket-affinity`, `--long-route-bonus`,
`--build-speed`, `--wild-frugality`, `--keep-greed`. Add `--seed` for
reproducible decisions. In auto mode the bot prints its seat's token on join
so the seat can be resumed later with `--player`/`--token`.

## Acknowlegements

* Map tiles by [Stamen Design](http://stamen.com), [CC BY 3.0](http://creativecommons.org/licenses/by/3.0). Data by [OpenStreetMap](http://openstreetmap.org), under [CC BY SA](http://creativecommons.org/licenses/by-sa/3.0).
