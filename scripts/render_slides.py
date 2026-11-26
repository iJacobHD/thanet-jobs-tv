#!/usr/bin/env python3
"""
Turn docs/jobs.json into JPG slides for a TV's USB photo slideshow.

Each slide is 1920x1080 with the 9:16 design already turned 270 degrees,
so a TV mounted on its side shows it upright.
Output: docs/usb/JOBS_01.jpg, JOBS_02.jpg ... and docs/usb/slides.zip

Needs:  pip install playwright pillow  &&  python -m playwright install chromium
"""
import functools
import http.server
import io
import json
import os
import shutil
import socketserver
import subprocess
import sys
import time
import threading
import zipfile

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(DOCS, "usb")


def main():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    rotate = int(cfg.get("usb_rotate", 270))
    min_days = int(cfg.get("usb_min_days_open", 4))

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=DOCS)
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    secs = int(cfg.get("video_seconds_per_slide", 15))
    boards = [("JOBS", "", "jobs-this-week.mp4", "slides.zip", "info.json", "jobs.json")]
    if os.path.exists(os.path.join(DOCS, "apprenticeships.json")):
        boards.append(("APPS", "&board=apprenticeships", "apprenticeships-this-week.mp4", "apprenticeship-slides.zip",
                       "info-apprenticeships.json", "apprenticeships.json"))
    w, h = (1920, 1080) if rotate % 180 else (1080, 1920)
    with sync_playwright() as p:
        exe = os.environ.get("CHROME_PATH")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h})
        for prefix, extra, video_name, zip_name, info_name, src in boards:
            files, n, total = [], 1, None
            while total is None or n <= total:
                page.goto(f"http://127.0.0.1:{port}/index.html?usb=1&rotate={rotate}&mindays={min_days}&page={n}{extra}")
                page.wait_for_function("document.body.dataset.ready === '1' || document.body.dataset.pages === '0'", timeout=20000)
                total = int(page.evaluate("document.body.dataset.pages") or 0)
                if total == 0:
                    total = 1  # still make one "nothing right now" slide
                png = page.screenshot(type="png")
                img = Image.open(io.BytesIO(png)).convert("RGB")
                name = f"{prefix}_{n:02d}.jpg"
                img.save(os.path.join(OUT, name), "JPEG", quality=95, subsampling=0)
                files.append(name)
                n += 1
            with zipfile.ZipFile(os.path.join(OUT, zip_name), "w", zipfile.ZIP_DEFLATED) as z:
                for f in files:
                    z.write(os.path.join(OUT, f), f)
            # MP4 for the TV: every slide shown for secs seconds, already rotated, plays on any TV (H.264).
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-framerate", f"1/{secs}", "-i", os.path.join(OUT, f"{prefix}_%02d.jpg"),
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
                "-r", "25", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-t", str(secs * len(files)), os.path.join(OUT, video_name),
            ], check=True)
            count = json.load(open(os.path.join(DOCS, src), encoding="utf-8")).get("count", 0)
            with open(os.path.join(OUT, info_name), "w") as fh:
                json.dump({"made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "slides": len(files),
                           "seconds_per_slide": secs, "min_days_open": min_days, "count": count}, fh)
            print(f"Made {len(files)} slides + {video_name} ({len(files) * secs}s) in docs/usb/ "
                  f"(everything stays open at least {min_days} more days)")
        browser.close()
    srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
