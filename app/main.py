"""ClipStream - a scalable, cloud-native short video sharing web app (COM769)."""
import os
import socket
import time
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_repo
from sentiment import analyse
from storage import LocalStorage, get_storage

ALLOWED = {".mp4", ".webm", ".mov"}
HERE = os.path.dirname(os.path.abspath(__file__))


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "100")) * 1024 * 1024
    repo, store = get_repo(HERE), get_storage(HERE)
    stats = {"requests": 0, "started": time.time(), "total_ms": 0.0}

    @app.before_request
    def _t0():
        request._t0 = time.perf_counter()

    @app.after_request
    def _t1(resp):
        ms = (time.perf_counter() - request._t0) * 1000
        stats["requests"] += 1
        stats["total_ms"] += ms
        resp.headers["X-Response-Time-ms"] = f"{ms:.1f}"
        resp.headers["X-Served-By"] = socket.gethostname()  # shows which pod/instance served it
        if request.path.startswith("/static"):
            resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    def login_required(f):
        @wraps(f)
        def w(*a, **k):
            if "uid" not in session:
                flash("Please log in first.")
                return redirect(url_for("login", next=request.path))
            return f(*a, **k)
        return w

    @app.context_processor
    def _ctx():
        return {"me": session.get("username"), "host": socket.gethostname(),
                "db_kind": repo.kind(), "store_kind": store.kind()}

    @app.route("/")
    def home():
        vids = repo.list_videos()
        counts = repo.comment_counts()
        for v in vids:
            v["url"] = store.url(v["blob"])
            v["comments"] = counts.get(v["id"], 0)
        return render_template("home.html", videos=vids)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            u = request.form.get("username", "").strip()
            e = request.form.get("email", "").strip()
            p = request.form.get("password", "")
            if len(u) < 3 or len(p) < 6 or "@" not in e:
                flash("Username 3+ chars, valid email, password 6+ chars.")
            elif repo.get_user_by_name(u):
                flash("That username is taken.")
            else:
                uid = repo.create_user(u, e, generate_password_hash(p))
                session.update(uid=uid, username=u)
                flash(f"Welcome to ClipStream, {u}!")
                return redirect(url_for("home"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = repo.get_user_by_name(request.form.get("username", "").strip())
            if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
                session.update(uid=user["id"], username=user["username"])
                return redirect(request.args.get("next") or url_for("home"))
            flash("Invalid username or password.")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("home"))

    @app.route("/upload", methods=["GET", "POST"])
    @login_required
    def upload():
        if request.method == "POST":
            f = request.files.get("video")
            ext = os.path.splitext(f.filename)[1].lower() if f and f.filename else ""
            if ext not in ALLOWED:
                flash("Please choose an .mp4, .webm or .mov video.")
                return render_template("upload.html"), 400
            blob = store.save(f, ext)
            vid = repo.add_video(session["uid"], session["username"], request.form.get("caption", "")[:300],
                                 request.form.get("tags", "")[:200], blob)
            flash("Video uploaded!")
            return redirect(url_for("video", vid=vid))
        return render_template("upload.html")

    @app.route("/v/<vid>")
    def video(vid):
        v = repo.get_video(vid) or abort(404)
        repo.incr(vid, "views")
        v["url"] = store.url(v["blob"])
        return render_template("video.html", v=v, comments=repo.comments(vid))

    @app.post("/api/videos/<vid>/like")
    @login_required
    def like(vid):
        repo.get_video(vid) or abort(404)
        liked, n = repo.toggle_like(vid, session["uid"])
        return jsonify(liked=liked, likes=n)

    @app.post("/api/videos/<vid>/share")
    def share(vid):
        repo.get_video(vid) or abort(404)
        repo.incr(vid, "shares")
        return jsonify(url=url_for("video", vid=vid, _external=True))

    @app.post("/v/<vid>/comment")
    @login_required
    def comment(vid):
        repo.get_video(vid) or abort(404)
        text = request.form.get("text", "").strip()[:500]
        if text:
            repo.add_comment(vid, session["username"], text, analyse(text))
        return redirect(url_for("video", vid=vid) + "#comments")

    @app.get("/api/videos")
    def api_videos():
        return jsonify([{k: v[k] for k in ("id", "username", "caption", "likes", "shares", "views")}
                        | {"url": store.url(v["blob"])} for v in repo.list_videos()])

    @app.get("/healthz")
    def health():
        return jsonify(status="ok", host=socket.gethostname(), db=repo.kind(), storage=store.kind())

    @app.get("/metrics")
    def metrics():
        n = stats["requests"] or 1
        return (f"clipstream_requests_total {stats['requests']}\n"
                f"clipstream_avg_response_ms {stats['total_ms'] / n:.2f}\n"
                f"clipstream_uptime_seconds {time.time() - stats['started']:.0f}\n"), 200, {
                    "Content-Type": "text/plain"}

    if isinstance(store, LocalStorage):
        @app.route("/media/<path:name>")
        def media(name):
            return send_from_directory(os.path.abspath(store.root), name, conditional=True)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
