"""
Browser check of the built site. Run by hand; pytest does not collect it (no test_ prefix).

    cd web && npx --no-install next build        # writes web/out
    python tests/e2e_site_check.py               # from the repo root

It serves `web/out` on a local port and, for every page, fails on a console error, on
the strings `nan` / `undefined` / `[object Object]` in the visible text, and on a
horizontal scroll at 375 px. It then exercises the corridor table controls and the
cold-start states of the live pages with the API replaced by a slow, then dead, host.

Needs the `playwright` package and its Chromium (both present in the project venv).
Exit code 0 means every check passed.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import re
import socketserver
import sys
import threading
from pathlib import Path

from playwright.async_api import Page, async_playwright

OUT = Path(__file__).resolve().parents[1] / "web" / "out"
PAGES = [
    "/", "/network/", "/corridors/", "/hubs/", "/predict/", "/alerts/", "/agents/",
    "/assistant/", "/prompts/", "/evidence/", "/paper/", "/about/",
]
BAD_TEXT = re.compile(r"(?<![A-Za-z0-9_])(nan|NaN|undefined|\[object Object\])(?![A-Za-z0-9_])")
# Third-party failures that are not the site's fault: map tiles and fonts when offline,
# and the live API while it is replaced by the test doubles.
IGNORED_CONSOLE = (
    "tile", "openfreemap", "fonts.g", "onrender.com", "net::ERR", "Failed to load resource",
    # Next prefetches other pages' payloads; closing the context mid-prefetch is not a site error.
    "Failed to fetch RSC payload",
)

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print(f"  FAIL  {msg}")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs) -> None:  # silence the access log
        pass


def serve() -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(_Quiet, directory=str(OUT))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


async def check_page(browser, base: str, path: str) -> None:
    errors: list[str] = []
    for width, label in ((1280, "desktop"), (375, "375px")):
        ctx = await browser.new_context(viewport={"width": width, "height": 800})
        page = await ctx.new_page()
        page.on(
            "console",
            lambda m, errs=errors: errs.append(m.text)
            if m.type == "error" and not any(s in m.text for s in IGNORED_CONSOLE) else None,
        )
        page.on("pageerror", lambda e, errs=errors: errs.append(f"pageerror: {e}"))
        await page.route("**/*onrender.com/**", lambda r: r.abort())
        await page.goto(base + path, wait_until="load")
        await page.wait_for_timeout(1200)
        text = await page.inner_text("body")
        hit = BAD_TEXT.search(text)
        if hit:
            fail(f"{path} ({label}): visible text contains '{hit.group(0)}'")
        if width == 375:
            overflow = await page.evaluate(
                "document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            if overflow > 1:
                culprit = await page.evaluate(
                    """() => { const w = document.documentElement.clientWidth;
                    const bad = [...document.querySelectorAll('body *')].filter(
                      e => e.getBoundingClientRect().right > w + 1 && !e.closest('.overflow-auto,.overflow-x-auto,pre,svg'));
                    return bad.slice(0, 3).map(e => e.tagName + '.' + String(e.className).slice(0, 60)); }"""
                )
                fail(f"{path}: horizontal scroll at 375px by {overflow}px; e.g. {culprit}")
        await ctx.close()
    for e in errors:
        fail(f"{path}: console error: {e[:160]}")
    print(f"  ok    {path}")


async def check_404(browser, base: str) -> None:
    ctx = await browser.new_context()
    page = await ctx.new_page()
    # A static host serves 404.html for any unknown address; request it directly.
    await page.goto(base + "/404.html")
    if "does not exist" not in await page.inner_text("body"):
        fail("404 page is missing")
    await ctx.close()


async def check_corridors(browser, base: str) -> None:
    ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()
    await page.goto(base + "/corridors/", wait_until="load")
    await page.wait_for_timeout(800)

    async def count() -> int:
        pill = page.locator("span").filter(has_text=re.compile(r"^[\d,]+ corridors$")).first
        return int((await pill.inner_text()).split()[0].replace(",", ""))

    slower = await count()
    await page.click("button:has-text('Both')")
    both = await count()
    if both <= slower:
        fail(f"corridors: Both ({both}) should exceed Slower ({slower})")
    pressed = await page.get_attribute("button:has-text('Both')", "aria-pressed")
    if pressed != "true":
        fail("corridors: active toggle does not report aria-pressed")
    await page.fill("#corridor-search", "kanpur")
    kanpur = await count()
    if not 0 < kanpur < both:
        fail(f"corridors: search for kanpur gave {kanpur} of {both}")
    await page.fill("#corridor-search", "")
    states = await page.eval_on_selector_all("#corridor-state option", "els => els.map(e => e.value)")
    if len(states) < 5:
        fail("corridors: state filter has no states")
    await page.select_option("#corridor-state", states[1])
    one_state = await count()
    if not 0 < one_state < both:
        fail(f"corridors: state filter gave {one_state} of {both}")
    await page.select_option("#corridor-state", "")
    rows = await page.locator("tbody tr").count()
    if rows > 25:
        fail(f"corridors: {rows} rows rendered on one page, expected at most 25")
    await page.click("button:has-text('Next')")
    if "Page 2 of" not in await page.inner_text("nav[aria-label='Corridor pages']"):
        fail("corridors: Next did not reach page 2")
    body = await page.inner_text("tbody")
    if re.search(r"(^|\s)0(\s|$)", body.split("\n")[0]) and "< 1e-6" not in body:
        fail("corridors: a bare 0 q-value may be showing")
    if "< 1e-6" not in await page.inner_text("tbody"):
        # not every page shows one; check the sorted-by-q view instead
        await page.click("th button:has-text('q')")
        if "< 1e-6" not in await page.inner_text("tbody"):
            fail("corridors: no '< 1e-6' q-value found on the q-sorted view")
    print("  ok    corridors controls (toggle, search, state, pagination, q format)")
    await ctx.close()


async def check_cold_start(browser, base: str) -> None:
    """A host that is slow, then dead: the page must explain, never go blank."""
    # 1. predictor: first request held for 4 s -> waking notice visible while waiting
    ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()

    async def slow_then_dead(route):
        await asyncio.sleep(4.5)
        await route.abort()

    await page.route("**/*onrender.com/**", slow_then_dead)
    await page.goto(base + "/predict/", wait_until="load")
    await page.wait_for_timeout(3800)
    if "Waking the free server" not in await page.inner_text("body"):
        fail("predict: no waking notice after 3 s of waiting")
    await page.wait_for_timeout(2500)
    body = await page.inner_text("body")
    if "Try again" not in body:
        fail("predict: no retry button once the host stayed down")
    await ctx.close()

    # 2. assistant: a question to a dead host -> error turn with retry
    ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()
    await page.route("**/*onrender.com/**", lambda r: r.abort())
    await page.goto(base + "/assistant/", wait_until="load")
    await page.click("button:has-text('Which corridors are the worst bottlenecks?')")
    await page.wait_for_timeout(1500)
    body = await page.inner_text("body")
    if "Try again" not in body or "did not answer" not in body:
        fail("assistant: no friendly error with a retry after a dead host")
    await ctx.close()

    # 3. alerts: dead host -> recorded table stays, notice + retry shown
    ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()
    await page.route("**/*onrender.com/**", lambda r: r.abort())
    await page.goto(base + "/alerts/", wait_until="load")
    await page.wait_for_timeout(1500)
    body = await page.inner_text("body")
    if "Try again" not in body or "Alert replay" not in body:
        fail("alerts: no retry notice, or the replay label is missing")
    if await page.locator("tbody tr").count() < 5:
        fail("alerts: the recorded table vanished when the host was down")
    await ctx.close()

    # 4. agents traces tab
    ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()
    await page.route("**/*onrender.com/**", lambda r: r.abort())
    await page.goto(base + "/agents/", wait_until="load")
    await page.click("button:has-text('Live traces')")
    await page.wait_for_timeout(1500)
    if "Try again" not in await page.inner_text("body"):
        fail("agents: traces tab shows no retry when the host is down")
    await ctx.close()
    print("  ok    cold-start states (predict, assistant, alerts, traces)")


async def main() -> int:
    if not (OUT / "index.html").exists():
        print(f"{OUT} has no build; run `npx --no-install next build` in web/ first")
        return 2
    server, port = serve()
    base = f"http://127.0.0.1:{port}"
    print(f"serving {OUT} at {base}")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for path in PAGES:
            await check_page(browser, base, path)
        await check_404(browser, base)
        await check_corridors(browser, base)
        await check_cold_start(browser, base)
        await browser.close()
    server.shutdown()
    print()
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("all site checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
