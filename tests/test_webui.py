"""Tests for the static web UI served by the game server"""

from fastapi.testclient import TestClient

from tkt_by_tkt import server

client = TestClient(server.app)


def test_root_redirects_to_ui():
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/ui/"


def test_ui_serves_index():
    response = client.get("/ui/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "join-form" in response.text
    assert 'src="app.js"' in response.text


def test_ui_serves_assets():
    assert client.get("/ui/app.js").status_code == 200
    assert client.get("/ui/style.css").status_code == 200


def test_cors_preflight():
    response = client.options(
        "/v1/games/nope",
        headers={"Origin": "http://elsewhere.example",
                 "Access-Control-Request-Method": "GET"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_etag_exposed_cross_origin():
    """The web UI polls with ETag, so CORS must expose the header"""
    response = client.get("/v1/games/nope",
                          headers={"Origin": "http://elsewhere.example"})
    assert "ETag" in response.headers.get(
        "access-control-expose-headers", "")
