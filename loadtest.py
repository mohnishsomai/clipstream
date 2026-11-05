"""Simple load test: python loadtest.py https://<your-app-url> 50 500
Sends N requests with C concurrent workers, reports latency and which instances served them.
"""
import collections
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

url, conc, n = sys.argv[1].rstrip("/"), int(sys.argv[2]), int(sys.argv[3])
hosts = collections.Counter()


def hit(_):
    t = time.perf_counter()
    with urllib.request.urlopen(url + "/api/videos", timeout=30) as r:
        r.read()
        hosts[r.headers.get("X-Served-By", "?")] += 1
    return (time.perf_counter() - t) * 1000


t0 = time.time()
with ThreadPoolExecutor(conc) as ex:
    lat = sorted(ex.map(hit, range(n)))
dur = time.time() - t0
print(f"{n} requests in {dur:.1f}s = {n / dur:.0f} req/s")
print(f"median {statistics.median(lat):.0f} ms, p95 {lat[int(n * .95) - 1]:.0f} ms")
print("served by:", dict(hosts))
