"""Re-take the README screenshots (docs/screenshots/*.png) from the demo inventory.

Dev-only helper - needs Playwright + Chromium and Pillow, not part of the app.

    DATABASE_URL=sqlite:///./data/demo.db SECRET_KEY=demo ENCRYPTION_KEY=demo python3 tools/demo_data.py
    DATABASE_URL=sqlite:///./data/demo.db SECRET_KEY=demo ENCRYPTION_KEY=demo uvicorn app.main:app --port 8765 &
    python3 tools/screenshots.py http://127.0.0.1:8765 [chromium-executable]

Screens are taken in English at 1440x900 (2x) and saved downscaled + palette-
optimised so the repository stays small.
"""
import io
import os
import sys

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
EXE = sys.argv[2] if len(sys.argv) > 2 else None
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "screenshots")
W, H = 1440, 900


def save(png_bytes, name, width=1600):
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    img = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    path = os.path.join(OUT, name)
    img.save(path, optimize=True)
    print(f"{name}: {img.width}x{img.height}, {os.path.getsize(path) // 1024} KB")


# Secondary VM-list columns hidden so names do not wrap at 1440 px
HIDDEN_COLS = '["vmid","pool","folder","vlan","ptags","uptime"]'


def page(browser, theme):
    pg = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
    pg.add_init_script(f"try {{ localStorage.setItem('vmi-lang', 'en');"
                       f" localStorage.setItem('vmi-dash-theme', '{theme}');"
                       f" localStorage.setItem('vmHiddenCols', '{HIDDEN_COLS}'); }} catch (e) {{}}")
    pg.goto(BASE + "/login")
    pg.fill("input[name=username]", "admin")
    pg.fill("input[name=password]", "admin123")
    pg.click("button[type=submit]")
    pg.wait_for_load_state("networkidle")
    return pg


def settle(pg, ms=900):
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(ms)


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch(**({"executable_path": EXE} if EXE else {}))

        pg = page(b, "dark")                                   # 1) dashboard
        pg.goto(BASE + "/"); settle(pg, 2500)
        save(pg.screenshot(), "dashboard.png")
        pg.close()

        pg = page(b, "light")                                  # 2) VM list + cluster menu
        pg.goto(BASE + "/vms?q=status:running&sort=cpu_usage&order=desc"); settle(pg)
        dd = pg.locator('.qf-dd[data-group="cluster"]')
        dd.locator(".qf-btn").click(); pg.wait_for_timeout(300)
        dd.locator('.qf-item[data-value="=PROD-East"]').click(); settle(pg, 600)
        dd.locator('.qf-item[data-value="=DMZ"]').click(); settle(pg, 600)
        save(pg.screenshot(), "vm-list.png")
        pg.keyboard.press("Escape")

        pg.locator("#vmBody tr.vm-row").first.click(); pg.wait_for_timeout(1200)   # 3) VM detail
        save(pg.screenshot(), "vm-detail.png")
        pg.close()

        pg = page(b, "dark")                                   # 4) search help
        pg.goto(BASE + "/vms"); settle(pg)
        pg.click("#searchHelp"); pg.wait_for_timeout(900)
        save(pg.screenshot(), "search-help.png")
        pg.close()

        pg = page(b, "light")                                  # 5) change history
        pg.goto(BASE + "/history"); settle(pg, 1500)
        save(pg.screenshot(), "change-history.png")
        pg.close()

        pg = page(b, "dark")                                   # 6) topology
        pg.goto(BASE + "/topology", wait_until="domcontentloaded"); pg.wait_for_timeout(3500)
        pg.click("#topoExpandAll"); pg.wait_for_timeout(4000)
        pg.wait_for_timeout(800)
        save(pg.screenshot(), "topology.png")
        pg.close()
        b.close()


if __name__ == "__main__":
    main()
