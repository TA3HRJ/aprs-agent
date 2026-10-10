#!/usr/bin/env python3
"""Quake-anchored silence, replayed over a raw feed log (F-2026-10-10-02).

usage: quake_watch_replay.py LOG_GLOB REGISTRY_DB [ANCHORS] [snap|cum]

LOG_GLOB is the logger extension's packet log and its rotated copies (quote
it), REGISTRY_DB a stations database, opened read-only. Run where the agent
runs, with its interpreter. Measures, for a point P, radius R, time T and evaluation delay W:

  n  stations within R of P, fixed (same exclusions as silence_cells), heard
     within their own threshold before T
  k  of those, the ones that at E = T + W have heard nothing since their last
     packet before T, and whose gap already exceeds their threshold
  p0 the same k/n over every station more than 1,000 km from P, same T and W
  pv binomial upper tail P(X >= k | n, p0)

Panama's three quakes, then random anchors at dense places and random times,
to see how often an ordinary hour looks like a quake.
"""
import array, bisect, collections, datetime as dt, glob, gzip, math, os, random, sqlite3, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import station_db as sdb

if len(sys.argv) < 3:
    sys.exit(__doc__)
LOG_GLOB, DB = sys.argv[1], sys.argv[2]
ARGS = sys.argv[3:]

t0 = time.time()
MOB = sdb.StationDB._MOBILE_TYPES
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=120)
elig = {}
for call, lat, lon, st, obj, ema, pc, sym_t, sym, comment in con.execute(
        "select callsign,lat,lon,station_type,is_object,ema_interval_s,packet_count,"
        "symbol_table,symbol,comment from stations"):
    if obj or lat is None or lon is None or ema is None or (pc or 0) < 5:
        continue
    if st in MOB:
        continue
    r = sdb.StationRecord(call)
    r.station_type, r.symbol_table, r.symbol, r.comment = st, sym_t, sym, comment
    r.is_object = obj
    try:
        if sdb.is_event_broadcast(r):
            continue
    except Exception:
        pass
    elig[call] = (lat, lon, max(3.0 * ema, 900.0))
print("eligible stations", len(elig), "%.0fs" % (time.time() - t0), flush=True)

times = {c: array.array("I") for c in elig}
files = sorted(glob.glob(LOG_GLOB), key=os.path.getmtime)
mcache = {}
per_min = collections.Counter()
for f in files:
    op = gzip.open if f.endswith(".gz") else open
    with op(f, "rt", errors="replace") as fh:
        for line in fh:
            sp = line.find(" ")
            gt = line.find(">", sp)
            if sp != 19 or gt < 0:
                continue
            m = line[:16]
            base = mcache.get(m)
            if base is None:
                base = int(dt.datetime.fromisoformat(m).timestamp())
                mcache[m] = base
            ts = base + int(line[17:19])
            per_min[base] += 1
            a = times.get(line[20:gt])
            if a is None:
                continue
            colon = line.find(":", gt)
            if colon > 0 and line[colon + 1:colon + 2] in (";", ")"):
                continue
            a.append(ts)
print("parsed %d files, %.0fs" % (len(files), time.time() - t0), flush=True)
for c in list(times):
    if not times[c]:
        del times[c]
    elif any(times[c][i] > times[c][i + 1] for i in range(len(times[c]) - 1)):
        times[c] = array.array("I", sorted(times[c]))
mins = sorted(per_min)
LO, HI = mins[0], mins[-1]
deaf = [m for m in range(LO, HI, 60) if per_min.get(m, 0) < 50]
print("log %s -> %s, deaf minutes %d" % (dt.datetime.fromtimestamp(LO), dt.datetime.fromtimestamp(HI), len(deaf)), flush=True)
deaf_set = set(deaf)

grid = collections.defaultdict(list)
for c in times:
    la, lo, thr = elig[c]
    grid[(int(math.floor(la)), int(math.floor(lo)))].append(c)


def km(a, b, c, d):
    p = math.pi / 180
    return 6371 * 2 * math.asin(math.sqrt(math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2))


def near(lat, lon, R):
    dl = R / 111.0 + 1
    dlo = R / (111.0 * max(0.1, math.cos(math.radians(lat)))) + 1
    out = []
    for i in range(int(math.floor(lat - dl)), int(math.floor(lat + dl)) + 1):
        for j in range(int(math.floor(lon - dlo)), int(math.floor(lon + dlo)) + 1):
            for c in grid.get((i, ((j + 180) % 360) - 180), ()):
                la, lo, _ = elig[c]
                if km(lat, lon, la, lo) <= R:
                    out.append(c)
    return out


def state(c, T, E):
    """(alive at T, quiet at E)"""
    a = times[c]
    thr = elig[c][2]
    i = bisect.bisect_right(a, T)
    if i == 0:
        return False, False
    before = a[i - 1]
    if T - before > thr:
        return False, False
    nxt = a[i] if i < len(a) else None
    if CUM:
        # quiet at ANY moment in (T, E]: its gap passed its threshold before E
        went = before + thr
        return True, went < E and (nxt is None or nxt > went)
    quiet = (nxt is None or nxt > E) and (E - before > thr)
    return True, quiet


ALL = list(times)
gcache = {}


def global_rate(T, E, exclude):
    key = (T, E)
    if key not in gcache:
        res = {}
        for c in ALL:
            al, q = state(c, T, E)
            if al:
                res[c] = q
        gcache.clear()          # one (T, E) at a time is all an anchor needs
        gcache[key] = (res, sum(res.values()), len(res))
    res, k, n = gcache[key]
    for c in exclude:
        q = res.get(c)
        if q is not None:
            n -= 1
            k -= q
    return k, n


def tail(k, n, p):
    if k == 0:
        return 1.0
    if p <= 0:
        return 0.0
    s = 0.0
    lp, lq = math.log(p), math.log1p(-p) if p < 1 else -1e9
    for x in range(k, n + 1):
        s += math.exp(math.lgamma(n + 1) - math.lgamma(x + 1) - math.lgamma(n - x + 1) + x * lp + (n - x) * lq)
    return min(1.0, s)


def measure(lat, lon, R, T, W):
    E = T + W
    if E > HI or any(m in deaf_set for m in range((T // 60) * 60 - 3600, (E // 60) * 60 + 60, 60)):
        return None
    loc = near(lat, lon, R)
    far = set(near(lat, lon, 1000))
    n = k = 0
    for c in loc:
        al, q = state(c, T, E)
        if al:
            n += 1
            k += q
    kg, ng = global_rate(T, E, far)
    p0 = kg / ng if ng else 0.0
    return k, n, p0, tail(k, n, p0)


CUM = len(ARGS) > 1 and ARGS[1] == "cum"
print("metric:", "cumulative (quiet at any moment up to E)" if CUM else "snapshot at E")
RS = (150, 300, 500)
WS = (1800, 3600, 3 * 3600)
print("\n=== Panama")
for name, lat, lon, ts in (("M7.7 10-09 17:56", 7.5868, -80.769, "2026-10-09T17:56:06"),
                           ("M6.6 10-09 20:25", 7.7176, -81.4687, "2026-10-09T20:25:39"),
                           ("M6.0 10-10 04:14", 7.5068, -80.5985, "2026-10-10T04:14:01")):
    T = int(dt.datetime.fromisoformat(ts + "+00:00").timestamp())
    for R in RS:
        row = []
        for W in WS:
            m = measure(lat, lon, R, T, W)
            row.append("W%3dm k=%3s n=%4s exp=%5s pv=%s" % (W // 60, m[0], m[1], "%.1f" % (m[1] * m[2]), "%.1e" % m[3]) if m else "W%dm -" % (W // 60))
        print("%s R%3d  %s" % (name, R, " | ".join(row)), flush=True)

PAN_T = int(dt.datetime.fromisoformat("2026-10-09T17:56:06+00:00").timestamp())
random.seed(10)
dense = [c for c in times if len(near(elig[c][0], elig[c][1], 150)) >= 15]
print("\ndense anchors available", len(dense), flush=True)
N = int(ARGS[0]) if ARGS else 300
res = []
tries = 0
while len(res) < N and tries < N * 5:
    tries += 1
    c = random.choice(dense)
    lat, lon, _ = elig[c]
    T = random.randint(LO + 3 * 3600, HI - 3 * 3600 - 60)
    if km(lat, lon, 7.59, -80.77) < 1500 and PAN_T - 3600 < T < PAN_T + 30 * 3600:
        continue
    if any(m in deaf_set for m in range((T // 60) * 60 - 3600, (T // 60) * 60 + 3 * 3600 + 60, 60)):
        continue
    row = {}
    for W in WS:                # W outer: one global pass per (T, E)
        for R in RS:
            row[(R, W)] = measure(lat, lon, R, T, W)
    res.append((c, T, row))
print("random anchors", len(res), "%.0fs" % (time.time() - t0), flush=True)
for R in RS:
    for W in WS:
        ms = [r[2][(R, W)] for r in res if r[2][(R, W)]]
        def fl(minK, pv):
            return sum(1 for k, n, p0, p in ms if k >= minK and p < pv)
        ks = sorted(k for k, n, p0, p in ms)
        print("R%3d W%3dm  anchors %3d  median n %4d  k: median %d p95 %d max %d | flagged k>=5&p<1e-3: %d  1e-4: %d  1e-6: %d" % (
            R, W // 60, len(ms), sorted(n for k, n, p0, p in ms)[len(ms) // 2], ks[len(ks) // 2], ks[int(.95 * len(ks))], ks[-1],
            fl(5, 1e-3), fl(5, 1e-4), fl(5, 1e-6)), flush=True)
worst = sorted(((r[2][(300, 3600)] or (0, 0, 0, 1))[3], r[0], dt.datetime.utcfromtimestamp(r[1]).strftime("%m-%d %H:%M"), r[2][(300, 3600)]) for r in res)[:8]
print("\nlowest p-values, R300 W60m:")
for pv, c, t, m in worst:
    print("  %s %s UTC  %s" % (c, t, m))
