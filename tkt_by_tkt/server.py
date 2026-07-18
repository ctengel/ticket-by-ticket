"""TBT game server: FastAPI implementation of design/api.openapi.yaml

Games live in memory (storage is an implementation detail per design/api.md);
tkt_by_tkt.game is the rules engine, this module only translates HTTP.
"""

import argparse
import secrets
import threading
from typing import Any, Dict, List, Literal, Optional

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from . import game as gamelib


class Unauthorized(gamelib.GameError):
    status = 401


class Forbidden(gamelib.GameError):
    status = 403


class GameOptions(BaseModel):
    starting_cars: int = 45
    starting_hand: int = 4
    faceup_count: int = 5
    ticket_offer: int = 3
    ticket_keep_min: int = 1
    setup_ticket_keep_min: int = 1
    last_round_cars: int = 2
    parallel_min_players: int = 4
    route_points: List[int] = [1, 2, 4, 7, 10, 15]


class GameCreate(BaseModel):
    map: Dict[str, Any]
    options: GameOptions = GameOptions()


class JoinRequest(BaseModel):
    name: str
    kind: Literal["human", "bot"] = "human"


class CardDrawRequest(BaseModel):
    source: Literal["deck", "faceup"]
    card: Optional[str] = None


class ClaimRequest(BaseModel):
    route: str
    track: int
    cards: List[str]


class TicketKeepRequest(BaseModel):
    tickets: List[int]


app = FastAPI(title="TBT Game Server API", version="1.0")
bearer = HTTPBearer(auto_error=False)

GAMES: Dict[str, gamelib.Game] = {}
LOCKS: Dict[str, threading.Lock] = {}
STORE_LOCK = threading.Lock()


@app.exception_handler(gamelib.GameError)
def game_error(request: Request, exc: gamelib.GameError):
    return JSONResponse(status_code=exc.status,
                        content={"error": exc.code, "message": exc.message})


@app.exception_handler(RequestValidationError)
def invalid_request(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422,
                        content={"error": "invalid_request",
                                 "message": str(exc.errors())})


def _game(game_id: str) -> gamelib.Game:
    game = GAMES.get(game_id)
    if game is None:
        raise gamelib.NotFound("game_not_found", "no game %s" % game_id)
    return game


def _actor(game: gamelib.Game,
           credentials: Optional[HTTPAuthorizationCredentials]):
    """Resolve the bearer token to a player of this game or 401"""
    token = credentials.credentials if credentials else None
    player = game.player_by_token(token)
    if player is None:
        raise Unauthorized("unauthorized", "missing or invalid bearer token")
    return player


@app.post("/v1/games", status_code=201)
def create_game(body: GameCreate):
    game_id = secrets.token_urlsafe(6)
    game = gamelib.Game(game_id, body.map, body.options.model_dump())
    with STORE_LOCK:
        GAMES[game_id] = game
        LOCKS[game_id] = threading.Lock()
    return {"game_id": game_id}


@app.get("/v1/games/{g}")
def get_game(g: str, request: Request):
    game = _game(g)
    with LOCKS[g]:
        etag = '"%d"' % game.state_version
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return JSONResponse(content=game.public_state(),
                            headers={"ETag": etag})


@app.get("/v1/games/{g}/map")
def get_map(g: str):
    return _game(g).map


@app.post("/v1/games/{g}/players", status_code=201)
def join_game(g: str, body: JoinRequest):
    game = _game(g)
    with LOCKS[g]:
        player = game.join(body.name, body.kind)
        return {"player_id": player.player_id, "token": player.token}


@app.get("/v1/games/{g}/players/{p}")
def get_player(g: str, p: str,
               credentials=Depends(bearer)):
    game = _game(g)
    with LOCKS[g]:
        actor = _actor(game, credentials)
        player = game.player_by_id(p)
        if actor is not player:
            raise Forbidden("forbidden", "token does not belong to %s" % p)
        return game.private_state(player)


@app.post("/v1/games/{g}/start")
def start_game(g: str, credentials=Depends(bearer)):
    game = _game(g)
    with LOCKS[g]:
        game.start(_actor(game, credentials))
        return game.public_state()


@app.post("/v1/games/{g}/card-draws", status_code=201)
def draw_card(g: str, body: CardDrawRequest, credentials=Depends(bearer)):
    game = _game(g)
    with LOCKS[g]:
        return game.draw_card(_actor(game, credentials),
                              body.source, body.card)


@app.post("/v1/games/{g}/claims", status_code=201)
def claim_route(g: str, body: ClaimRequest, credentials=Depends(bearer)):
    game = _game(g)
    with LOCKS[g]:
        return game.claim(_actor(game, credentials),
                          body.route, body.track, body.cards)


@app.post("/v1/games/{g}/ticket-draws", status_code=201)
def draw_tickets(g: str, credentials=Depends(bearer)):
    game = _game(g)
    with LOCKS[g]:
        return game.draw_tickets(_actor(game, credentials))


@app.post("/v1/games/{g}/ticket-keeps", status_code=201)
def keep_tickets(g: str, body: TicketKeepRequest, credentials=Depends(bearer)):
    game = _game(g)
    with LOCKS[g]:
        return game.keep_tickets(_actor(game, credentials), body.tickets)


@app.get("/v1/games/{g}/log")
def get_log(g: str, since: int = 0):
    game = _game(g)
    with LOCKS[g]:
        return game.log_since(since)


def main():
    """tbt-server console entry point"""
    import uvicorn
    parser = argparse.ArgumentParser(description="TBT game server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
