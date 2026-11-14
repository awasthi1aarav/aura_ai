"""Clicks through every page on desktop and mobile; reports page errors, console errors and failed requests."""
import asyncio
import os
import sys

from playwright.async_api import async_playwright

B, M, MPW = sys.argv[1], sys.argv[2], sys.argv[3]
TEAM_PW = os.environ.get("AURA_ADMIN_PASSWORD", "aura-admin")
OUT = "/home/claude/shots/bt"
problems = []


def watch(page, tag):
    page.on("pageerror", lambda e: problems.append(f"[{tag}] page error: {str(e)[:200]}"))
    page.on("console", lambda m: m.type == "error" and problems.append(f"[{tag}] console: {m.text[:200]}"))
    page.on("response", lambda r: r.status >= 500 and problems.append(f"[{tag}] HTTP {r.status} {r.url}"))


async def step(page, tag, name, coro):
    try:
        await coro
    except Exception as e:
        problems.append(f"[{tag}] FAILED step '{name}': {str(e).splitlines()[0][:160]}")


async def run(b, tag, vp, mobile=False):
    ctx = await b.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, accept_downloads=True)
    p = await ctx.new_page()
    watch(p, tag)
    base = f"{B}/#/m/{M}"
    await p.goto(base); await p.wait_for_timeout(3500)
    await p.screenshot(path=f"{OUT}_{tag}_dash.png", full_page=True)
    await step(p, tag, "open action card", p.locator("text=What to do").first.click())
    # check-in pages
    await p.goto(f"{base}/crew"); await p.wait_for_timeout(1500)
    await step(p, tag, "open profile", p.locator(".card.pick").first.click()); await p.wait_for_timeout(2500)
    for s in ["Brain & mind", "Eyes & vision", "Lungs & breathing", "Heart & circulation",
              "Blood & metabolism", "Temperature & immunity", "Bones & muscles"]:
        await step(p, tag, f"body {s}", p.click(f"[aria-label='{s}']"))
        await p.wait_for_timeout(150)
        txt = await p.locator(".syspanel h3").inner_text() if await p.locator(".syspanel h3").count() else ""
        if txt != s:
            problems.append(f"[{tag}] body map: clicked {s}, panel shows '{txt}'")
    for rng in ["7 days", "30 days", "90 days", "24 hours"]:
        await step(p, tag, f"chart {rng}", p.locator(".small-scen button", has_text=rng).first.click()); await p.wait_for_timeout(900)
    await step(p, tag, "chart sleep", p.locator(".small-scen button", has_text="Sleep").first.click()); await p.wait_for_timeout(900)
    await step(p, tag, "fill check-in", p.fill("input[placeholder='e.g. 92']", "101"))
    await step(p, tag, "mood", p.click("[aria-label='Mood 4 of 5']"))
    await step(p, tag, "symptom", p.locator(".chips.sym button", has_text="fatigue").click())
    await step(p, tag, "save check-in", p.click("button:has-text('Save check-in')")); await p.wait_for_timeout(2500)
    ok = await p.locator("text=Check-in saved").count()
    if not ok:
        problems.append(f"[{tag}] check-in did not confirm")
    await step(p, tag, "records filter", p.locator(".records-filter button", has_text="Check-ins").click()); await p.wait_for_timeout(1200)
    await step(p, tag, "records search", p.fill("input[placeholder^='Search symptoms']", "fatigue"))
    await step(p, tag, "records search go", p.click(".search button:has-text('Search')")); await p.wait_for_timeout(1200)
    if not await p.locator(".rec").count():
        problems.append(f"[{tag}] records search returned nothing")
    await p.screenshot(path=f"{OUT}_{tag}_profile.png", full_page=True)
    # assistant
    await p.goto(f"{base}/assistant"); await p.wait_for_timeout(2000)
    await step(p, tag, "ask", p.locator(".chips button").first.click())
    for _ in range(30):
        await p.wait_for_timeout(1000)
        if not await p.locator(".typing").count():
            break
    n = await p.locator(".msg.assistant .body").count()
    if not n:
        problems.append(f"[{tag}] assistant gave no reply")
    await p.screenshot(path=f"{OUT}_{tag}_assistant.png")
    # admin
    await p.goto(f"{base}/admin"); await p.wait_for_timeout(1000)
    await step(p, tag, "unlock", p.fill("input[type=password]", MPW))
    await step(p, tag, "unlock click", p.click("button:has-text('Unlock admin')")); await p.wait_for_timeout(1500)
    for t in ["Crew", "Sensors", "Limits", "Readings", "Simulator", "Connect a sensor", "Mission", "Activity"]:
        await step(p, tag, f"tab {t}", p.locator(".tabs button", has_text=t).first.click()); await p.wait_for_timeout(700)
    await step(p, tag, "tab Simulator", p.locator(".tabs button", has_text="Simulator").first.click()); await p.wait_for_timeout(500)
    await step(p, tag, "scenario", p.locator(".scen button", has_text="Hypoxia").click()); await p.wait_for_timeout(600)
    await step(p, tag, "scenario reset", p.locator(".scen button", has_text="Normal operations").click()); await p.wait_for_timeout(400)
    await p.screenshot(path=f"{OUT}_{tag}_admin.png")
    # host/join + team
    await p.goto(f"{B}/#/host"); await p.wait_for_timeout(800)
    await step(p, tag, "join", p.fill("input[placeholder='K7Q2PX']", M.lower()))
    await step(p, tag, "join go", p.click("button:has-text('Join')")); await p.wait_for_timeout(1500)
    if f"/m/{M}" not in p.url:
        problems.append(f"[{tag}] join by code failed: {p.url}")
    await p.goto(f"{B}/#/team"); await p.wait_for_timeout(800)
    await step(p, tag, "team user", p.fill("input[autocomplete=username]", "admin"))
    await step(p, tag, "team pw", p.fill("input[type=password]", TEAM_PW))
    await step(p, tag, "team go", p.click("button:has-text('Sign in')")); await p.wait_for_timeout(1500)
    for t in ["Missions", "Team accounts", "Activity"]:
        await step(p, tag, f"team tab {t}", p.locator(".tabs button", has_text=t).first.click()); await p.wait_for_timeout(700)
    await p.goto(f"{B}/#/m/NOPE22"); await p.wait_for_timeout(1500)
    if not await p.locator("text=Mission not found").count():
        problems.append(f"[{tag}] missing-mission page not shown")
    # layout check: horizontal overflow on mobile
    for path in ["", "/crew", "/assistant"]:
        await p.goto(base + path); await p.wait_for_timeout(1500)
        sw = await p.evaluate("document.documentElement.scrollWidth")
        if sw > vp["width"] + 2:
            problems.append(f"[{tag}] page {path or '/'} overflows horizontally ({sw}px > {vp['width']}px)")
    await ctx.close()


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        await run(b, "desktop", {"width": 1440, "height": 900})
        await run(b, "mobile", {"width": 390, "height": 844}, mobile=True)
        await b.close()
    print("\n".join(problems) if problems else "No problems found")


asyncio.run(main())
