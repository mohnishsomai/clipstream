import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    import importlib
    import main
    importlib.reload(main)
    app = main.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def register(c, u="alice"):
    return c.post("/register", data={"username": u, "email": f"{u}@x.com", "password": "secret1"},
                  follow_redirects=True)


def upload(c):
    return c.post("/upload", data={"video": (io.BytesIO(b"fake"), "clip.mp4"), "caption": "hello", "tags": "fun"},
                  content_type="multipart/form-data")


def test_health(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json["status"] == "ok"


def test_register_and_login(client):
    assert b"Welcome to ClipStream" in register(client).data
    client.get("/logout")
    r = client.post("/login", data={"username": "alice", "password": "secret1"}, follow_redirects=True)
    assert b"@alice" in r.data


def test_upload_requires_login(client):
    assert client.get("/upload").status_code == 302


def test_reject_bad_file_type(client):
    register(client)
    r = client.post("/upload", data={"video": (io.BytesIO(b"x"), "evil.exe")}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_upload_like_comment_share(client):
    register(client)
    r = upload(client)
    assert r.status_code == 302
    vid = r.headers["Location"].rsplit("/", 1)[-1]
    assert client.post(f"/api/videos/{vid}/like").json == {"liked": True, "likes": 1}
    assert client.post(f"/api/videos/{vid}/like").json["likes"] == 0
    client.post(f"/v/{vid}/comment", data={"text": "I love this, amazing"})
    page = client.get(f"/v/{vid}").data
    assert b"positive" in page
    assert client.post(f"/api/videos/{vid}/share").status_code == 200
    assert client.get("/api/videos").json[0]["shares"] == 1
