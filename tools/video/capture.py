"""Capture crisp screenshots (2x) of the live app for the demo video, plus element boxes for the camera."""
import asyncio
import json

from playwright.async_api import async_playwright

B = "https://aura-ai-bk7d.onrender.com/#/m/DEMO"
W, H, S = 1600, 900, 2
boxes = {}


async def box(page, name, sel):
    loc = page.locator(sel).first
    b = await loc.bounding_box()
    if b:
        boxes[name] = [round(v * S) for v in (b["x"], b["y"], b["width"], b["height"])]


async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        ctx = await br.new_context(viewport={"width": W, "height": H}, device_scale_factor=S)
        pg = await ctx.new_page()
        await pg.goto(B); await pg.wait_for_timeout(5000)
        await pg.screenshot(path="s_dash.png")
        await box(pg, "dash_hazards", ".hazards")
        await box(pg, "dash_crew", ".crew-grid")
        # forecast alert + its action card
        al = pg.locator(".al", has_text="falling").first
        if not await al.count():
            al = pg.locator(".al").first
        btn = al.locator("text=What to do")
        if await btn.count():
            await btn.click(); await pg.wait_for_timeout(400)
        b = await al.bounding_box()
        boxes["alert"] = [round(v * S) for v in (b["x"], b["y"], b["width"], b["height"])]
        await pg.screenshot(path="s_alert.png")
        boxes["alert_text"] = await al.inner_text()
        # Earth panel
        await pg.locator("h2:has-text('Earth')").first.scroll_into_view_if_needed()
        await pg.evaluate("window.scrollBy(0, -120)"); await pg.wait_for_timeout(500)
        await pg.screenshot(path="s_earth.png")
        await box(pg, "earth", ".card.earth")
        # body map (Kenji)
        await pg.goto(B + "/crew/2"); await pg.wait_for_timeout(3500)
        await pg.click("[aria-label='Lungs & breathing']"); await pg.wait_for_timeout(400)
        await pg.locator(".bodypanel").scroll_into_view_if_needed()
        await pg.evaluate("window.scrollTo(0, 0)"); await pg.wait_for_timeout(400)
        await pg.screenshot(path="s_body.png")
        await box(pg, "body", ".bodypanel")
        await box(pg, "routine", ".profile-grid > section:nth-child(2)")
        # wellbeing (Aisha)
        await pg.goto(B + "/crew/3"); await pg.wait_for_timeout(3500)
        await pg.locator("h2:has-text('Wellbeing')").scroll_into_view_if_needed()
        await pg.evaluate("window.scrollBy(0, -110)"); await pg.wait_for_timeout(500)
        await pg.screenshot(path="s_wellbeing.png")
        await box(pg, "wellbeing", ".wellbeing")
        # assistant
        await pg.goto(B + "/assistant?crew=2"); await pg.wait_for_timeout(2500)
        if await pg.locator("text=Clear history").count():
            pg.once("dialog", lambda d: asyncio.ensure_future(d.accept()))
            await pg.click("text=Clear history"); await pg.wait_for_timeout(800)
        await pg.fill(".composer input", "What will happen in the next hour if nothing changes?")
        await pg.click(".composer button")
        for _ in range(60):
            await pg.wait_for_timeout(1000)
            if not await pg.locator(".typing").count():
                break
        await pg.wait_for_timeout(500)
        await pg.screenshot(path="s_chat.png")
        await box(pg, "chat", ".chat")
        boxes["chat_source"] = await pg.locator(".msg.assistant .who").last.inner_text()
        json.dump(boxes, open("boxes.json", "w"), indent=1)
        await br.close()


asyncio.run(main())
