"""The app serves the static single-page frontend at / (single origin, no build)."""


def test_root_serves_the_app_shell(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "learn-german" in r.text
    assert "app.js" in r.text and "app.css" in r.text


def test_static_assets_are_served(client):
    css = client.get("/app.css")
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    js = client.get("/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]


def test_legacy_study_url_still_resolves(client):
    r = client.get("/study.html")
    assert r.status_code == 200
    assert "index.html" in r.text  # redirect stub into the SPA


def test_api_routes_still_win_over_the_static_mount(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/words/999999").status_code == 404
