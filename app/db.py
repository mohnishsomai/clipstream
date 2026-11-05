"""Data layer.

Development uses SQLite. Production uses Azure Cosmos DB (NoSQL API), a
globally distributed document database that scales throughput automatically.
Both implement the same small repository interface.
"""
import os
import sqlite3
import time
import uuid


class SQLiteRepo:
    def __init__(self, path):
        self.path = path
        with self._c() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE,
                    email TEXT, password_hash TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS videos(id TEXT PRIMARY KEY, user_id TEXT, username TEXT,
                    caption TEXT, tags TEXT, blob TEXT, likes INTEGER DEFAULT 0,
                    shares INTEGER DEFAULT 0, views INTEGER DEFAULT 0, created REAL);
                CREATE TABLE IF NOT EXISTS likes(video_id TEXT, user_id TEXT, PRIMARY KEY(video_id,user_id));
                CREATE TABLE IF NOT EXISTS comments(id TEXT PRIMARY KEY, video_id TEXT, username TEXT,
                    text TEXT, sentiment TEXT, created REAL);
                """
            )

    def _c(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def kind(self):
        return "SQLite (dev)"

    # users
    def create_user(self, username, email, password_hash):
        uid = uuid.uuid4().hex
        with self._c() as c:
            c.execute("INSERT INTO users VALUES(?,?,?,?,?)", (uid, username, email, password_hash, time.time()))
        return uid

    def get_user_by_name(self, username):
        with self._c() as c:
            r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(r) if r else None

    # videos
    def add_video(self, user_id, username, caption, tags, blob):
        vid = uuid.uuid4().hex[:12]
        with self._c() as c:
            c.execute(
                "INSERT INTO videos(id,user_id,username,caption,tags,blob,created) VALUES(?,?,?,?,?,?,?)",
                (vid, user_id, username, caption, tags, blob, time.time()),
            )
        return vid

    def list_videos(self, limit=20):
        with self._c() as c:
            rows = c.execute("SELECT * FROM videos ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_video(self, vid):
        with self._c() as c:
            r = c.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
        return dict(r) if r else None

    def incr(self, vid, field):
        assert field in ("views", "shares")
        with self._c() as c:
            c.execute(f"UPDATE videos SET {field}={field}+1 WHERE id=?", (vid,))

    def toggle_like(self, vid, uid):
        with self._c() as c:
            if c.execute("SELECT 1 FROM likes WHERE video_id=? AND user_id=?", (vid, uid)).fetchone():
                c.execute("DELETE FROM likes WHERE video_id=? AND user_id=?", (vid, uid))
                c.execute("UPDATE videos SET likes=likes-1 WHERE id=?", (vid,))
                liked = False
            else:
                c.execute("INSERT INTO likes VALUES(?,?)", (vid, uid))
                c.execute("UPDATE videos SET likes=likes+1 WHERE id=?", (vid,))
                liked = True
            n = c.execute("SELECT likes FROM videos WHERE id=?", (vid,)).fetchone()[0]
        return liked, n

    def add_comment(self, vid, username, text, sentiment):
        with self._c() as c:
            c.execute(
                "INSERT INTO comments VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, vid, username, text, sentiment, time.time()),
            )

    def comments(self, vid):
        with self._c() as c:
            rows = c.execute("SELECT * FROM comments WHERE video_id=? ORDER BY created", (vid,)).fetchall()
        return [dict(r) for r in rows]

    def comment_counts(self):
        with self._c() as c:
            rows = c.execute("SELECT video_id, COUNT(*) n FROM comments GROUP BY video_id").fetchall()
        return {r["video_id"]: r["n"] for r in rows}


class CosmosRepo:
    """Azure Cosmos DB (NoSQL). Requires: pip install azure-cosmos.

    Containers are partitioned for scale: users by /username, videos by /id,
    comments by /video_id, likes by /video_id.
    """

    def __init__(self, url, key, db_name="clipstream"):
        from azure.cosmos import CosmosClient, PartitionKey

        client = CosmosClient(url, credential=key)
        db = client.create_database_if_not_exists(db_name)
        mk = lambda n, pk: db.create_container_if_not_exists(id=n, partition_key=PartitionKey(path=pk))
        self.users = mk("users", "/username")
        self.videos = mk("videos", "/id")
        self.comments_c = mk("comments", "/video_id")
        self.likes = mk("likes", "/video_id")

    def kind(self):
        return "Azure Cosmos DB"

    def create_user(self, username, email, password_hash):
        if self.get_user_by_name(username):
            raise ValueError("exists")
        uid = uuid.uuid4().hex
        self.users.create_item({"id": uid, "username": username, "email": email,
                                "password_hash": password_hash, "created": time.time()})
        return uid

    def get_user_by_name(self, username):
        items = list(self.users.query_items("SELECT * FROM u WHERE u.username=@n",
                                            parameters=[{"name": "@n", "value": username}],
                                            partition_key=username))
        return items[0] if items else None

    def add_video(self, user_id, username, caption, tags, blob):
        vid = uuid.uuid4().hex[:12]
        self.videos.create_item({"id": vid, "user_id": user_id, "username": username, "caption": caption,
                                 "tags": tags, "blob": blob, "likes": 0, "shares": 0, "views": 0,
                                 "created": time.time()})
        return vid

    def list_videos(self, limit=20):
        return list(self.videos.query_items(f"SELECT TOP {int(limit)} * FROM v ORDER BY v.created DESC",
                                            enable_cross_partition_query=True))

    def get_video(self, vid):
        try:
            return self.videos.read_item(vid, partition_key=vid)
        except Exception:
            return None

    def incr(self, vid, field):
        self.videos.patch_item(vid, partition_key=vid,
                               patch_operations=[{"op": "incr", "path": f"/{field}", "value": 1}])

    def toggle_like(self, vid, uid):
        lid = f"{vid}:{uid}"
        try:
            self.likes.read_item(lid, partition_key=vid)
            self.likes.delete_item(lid, partition_key=vid)
            delta, liked = -1, False
        except Exception:
            self.likes.create_item({"id": lid, "video_id": vid, "user_id": uid})
            delta, liked = 1, True
        v = self.videos.patch_item(vid, partition_key=vid,
                                   patch_operations=[{"op": "incr", "path": "/likes", "value": delta}])
        return liked, v["likes"]

    def add_comment(self, vid, username, text, sentiment):
        self.comments_c.create_item({"id": uuid.uuid4().hex, "video_id": vid, "username": username,
                                     "text": text, "sentiment": sentiment, "created": time.time()})

    def comments(self, vid):
        return list(self.comments_c.query_items("SELECT * FROM c WHERE c.video_id=@v ORDER BY c.created",
                                                parameters=[{"name": "@v", "value": vid}], partition_key=vid))

    def comment_counts(self):
        rows = self.comments_c.query_items("SELECT c.video_id, COUNT(1) AS n FROM c GROUP BY c.video_id",
                                           enable_cross_partition_query=True)
        return {r["video_id"]: r["n"] for r in rows}


def get_repo(app_root):
    url, key = os.environ.get("COSMOS_URL"), os.environ.get("COSMOS_KEY")
    if url and key:
        return CosmosRepo(url, key)
    return SQLiteRepo(os.environ.get("SQLITE_PATH", os.path.join(app_root, "..", "clipstream.db")))
