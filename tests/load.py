"""Load test: N concurrent viewers polling like the real dashboard (every 4 s), plus a mix of
chart/record requests and streaming sensors. Reports latency percentiles and errors per stage."""
import asyncio
import os
import statistics
import sys
import time

import httpx

B = sys.argv[1]
STAGES = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "10,25,50").split(",")]
DURATION = int(os.environ.get("DURATION", "40"))


async def viewer(client, stop, lat, errs, crew_ids, i):
    n = 0
    while time.monotonic() < stop:
        paths = ["/api/m/DEMO/overview"]
        if n % 5 == 0:  # every ~20 s a viewer opens a chart or records
            cid = crew_ids[(i + n) % len(crew_ids)]
            paths.append(["/api/m/DEMO/history?metric=heart_rate&crew_id=%d&range=7d" % cid,
                          "/api/m/DEMO/records?crew_id=%d&days=30" % cid,
                          "/api/m/DEMO/history?metric=spo2&crew_id=%d&range=90d" % cid][n % 3])
        for p in paths:
            t = time.monotonic()
            try:
                r = await client.get(p)
                lat.append((time.monotonic() - t) * 1000)
                if r.status_code != 200:
                    errs.append(r.status_code)
            except Exception as e:
                errs.append(type(e).__name__)
        n += 1
        await asyncio.sleep(4)


async def sensor(client, stop, lat, errs, sid, key, base):
    k = 0
    while time.monotonic() < stop:
        t = time.monotonic()
        try:
            r = await client.post("/api/ingest", headers={"X-API-Key": key},
                                  json={"sensor_id": sid, "value": base + (k % 3)})
            lat.append((time.monotonic() - t) * 1000)
            if r.status_code != 200:
                errs.append(r.status_code)
        except Exception as e:
            errs.append(type(e).__name__)
        k += 1
        await asyncio.sleep(1)


def pct(xs, p):
    return sorted(xs)[min(len(xs) - 1, int(len(xs) * p))] if xs else 0


async def main():
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
    async with httpx.AsyncClient(base_url=B, timeout=30, limits=limits) as c:
        d = (await c.get("/api/m/DEMO/overview")).json()
        crew_ids = [x["id"] for x in d["crew"]]
        sensors = [tuple(s.split(":")) for s in os.environ.get("SENSORS", "").split(",") if s]
        for n in STAGES:
            lat, errs, slat, serrs = [], [], [], []
            stop = time.monotonic() + DURATION
            tasks = [viewer(c, stop, lat, errs, crew_ids, i) for i in range(n)]
            tasks += [sensor(c, stop, slat, serrs, int(sid), key, 95) for sid, key in sensors]
            t0 = time.monotonic()
            await asyncio.gather(*tasks)
            el = time.monotonic() - t0
            print(f"{n:>3} viewers | {len(lat)/el:5.1f} req/s | p50 {statistics.median(lat):6.0f} ms | "
                  f"p95 {pct(lat, .95):6.0f} ms | max {max(lat):6.0f} ms | errors {len(errs)} {sorted(set(map(str, errs)))[:5]}")
            if sensors:
                print(f"    sensors {len(sensors)} @1Hz | p50 {statistics.median(slat):5.0f} ms | p95 {pct(slat, .95):5.0f} ms | errors {len(serrs)}")


asyncio.run(main())
