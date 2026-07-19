"""Thin HTTP client for the TBT game server API (design/api.md)

The session is injectable: anything with a requests-style ``.request()``
works, including fastapi's TestClient, so tests can drive the bot against
an in-process server with no sockets and no requests dependency.
"""


class ApiError(Exception):
    """A non-2xx API response, carrying the api.md error envelope"""

    def __init__(self, status, code, message):
        super().__init__("%s (%d): %s" % (code, status, message))
        self.status = status
        self.code = code
        self.message = message


class Client:
    """One connection to a TBT server, optionally holding a player token"""

    def __init__(self, base_url, token=None, session=None):
        if session is None:
            import requests
            session = requests.Session()
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = session

    def _call(self, method, path, body=None, headers=None):
        headers = dict(headers or {})
        if self.token:
            headers["Authorization"] = "Bearer %s" % self.token
        response = self.session.request(method, self.base_url + path,
                                        json=body, headers=headers)
        if response.status_code >= 400:
            try:
                payload = response.json()
                error = ApiError(response.status_code,
                                 payload.get("error", "unknown"),
                                 payload.get("message", ""))
            except ValueError:
                error = ApiError(response.status_code, "unknown",
                                 response.text)
            raise error
        return response

    # ----- game access -------------------------------------------------

    def join(self, game_id, name, kind="bot"):
        """Take a seat; remembers the issued token for later calls"""
        seat = self._call("POST", "/v1/games/%s/players" % game_id,
                          {"name": name, "kind": kind}).json()
        self.token = seat["token"]
        return seat

    def state(self, game_id, etag=None):
        """Public state as (state, etag); (None, etag) on a 304 cache hit"""
        headers = {"If-None-Match": etag} if etag else None
        response = self._call("GET", "/v1/games/%s" % game_id,
                              headers=headers)
        if response.status_code == 304:
            return None, etag
        return response.json(), response.headers.get("etag")

    def get_map(self, game_id):
        return self._call("GET", "/v1/games/%s/map" % game_id).json()

    def private(self, game_id, player_id):
        return self._call("GET", "/v1/games/%s/players/%s"
                          % (game_id, player_id)).json()

    def log_since(self, game_id, since=0):
        return self._call("GET", "/v1/games/%s/log?since=%d"
                          % (game_id, since)).json()

    # ----- turn actions ------------------------------------------------

    def draw_card(self, game_id, source, card=None):
        body = {"source": source}
        if card is not None:
            body["card"] = card
        return self._call("POST", "/v1/games/%s/card-draws" % game_id,
                          body).json()

    def claim(self, game_id, route, track, cards):
        return self._call("POST", "/v1/games/%s/claims" % game_id,
                          {"route": route, "track": track,
                           "cards": list(cards)}).json()

    def draw_tickets(self, game_id):
        return self._call("POST", "/v1/games/%s/ticket-draws"
                          % game_id).json()

    def keep_tickets(self, game_id, ticket_ids):
        return self._call("POST", "/v1/games/%s/ticket-keeps" % game_id,
                          {"tickets": list(ticket_ids)}).json()
