"""Optional browser smoke test of the editor UI (Playwright driving the installed Edge/Chrome).

    python -m venv tools/uitest && tools/uitest/Scripts/python -m pip install playwright
    tools/uitest/Scripts/python scripts/ui_smoke.py --job <job_id> [--front http://localhost:3300] [--api http://localhost:8300]

Opens the job's editor, selects the first bubble, drags it, edits its text, saves, checks the
backend stored the change, and fails on any browser console error. Screenshots go to tools/shots/.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "tools" / "shots"


def api(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path) as r:
        return json.loads(r.read())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--front", default="http://localhost:3300")
    parser.add_argument("--api", default="http://localhost:8300")
    parser.add_argument("--channel", default="msedge", help="installed browser: msedge or chrome")
    parser.add_argument("--only-shot", default="", help="just screenshot this path (e.g. '/?x=1') and exit")
    args = parser.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.channel, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        if args.only_shot:
            page.goto(args.front + args.only_shot)
            page.wait_for_timeout(4000)
            name = "shot_" + "".join(c if c.isalnum() else "_" for c in args.only_shot)[:60] + ".png"
            page.screenshot(path=str(SHOTS / name), full_page=True)
            print("saved", SHOTS / name, "console errors:", errors)
            return 1 if errors else 0

        page.goto(f"{args.front}/jobs/{args.job}?tab=edit")
        canvas = page.locator("canvas").first
        canvas.wait_for(timeout=30000)
        page.wait_for_timeout(2500)  # images
        page.screenshot(path=str(SHOTS / "editor_1_loaded.png"), full_page=True)

        data = api(args.api, f"/api/jobs/{args.job}/pages/1/editor")
        bubble = data["lettering"]["bubbles"][0]
        inner = next(p["inner"] for p in data["panels"] if p["panel"] == bubble["panel"])
        box = canvas.bounding_box()
        scale = box["width"] / data["width"]
        cx = box["x"] + (inner["x"] + (bubble["x"] + bubble["w"] / 2) * inner["w"]) * scale
        cy = box["y"] + (inner["y"] + (bubble["y"] + bubble["h"] / 2) * inner["h"]) * scale
        page.mouse.click(cx, cy)
        page.wait_for_timeout(300)
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 40, cy + 30, steps=8)
        page.mouse.up()
        page.wait_for_timeout(300)
        area = page.locator("textarea").first
        area.fill("SMOKE TEST EDIT")
        area.blur()
        page.screenshot(path=str(SHOTS / "editor_2_edited.png"), full_page=True)
        page.get_by_role("button", name="Save page").click()
        page.get_by_text("Saved. The page PNG").wait_for(timeout=30000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(SHOTS / "editor_3_saved.png"), full_page=True)

        after = api(args.api, f"/api/jobs/{args.job}/pages/1/editor")["lettering"]
        moved = next(b for b in after["bubbles"] if b["id"] == bubble["id"])
        ok = moved["text"] == "SMOKE TEST EDIT" and abs(moved["x"] - bubble["x"]) > 0.01 and after["source"] == "edited"
        browser.close()

    print("stored change:", ok, "| console errors:", errors or "none")
    return 0 if ok and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
