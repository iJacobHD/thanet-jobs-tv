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

    w, h = (1920, 1080) if rotate % 180 else (1080, 1920)
    files = []
    with sync_playwright() as p:
        exe = os.environ.get("CHROME_PATH")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h})
        n, total = 1, None
        while total is None or n <= total:
            page.goto(f"http://127.0.0.1:{port}/index.html?usb=1&rotate={rotate}&mindays={min_days}&page={n}")
            page.wait_for_function("document.body.dataset.ready === '1' || document.body.dataset.pages === '0'", timeout=20000)
            total = int(page.evaluate("document.body.dataset.pages") or 0)
            if total == 0:
                total = 1  # still make one "no jobs right now" slide
            png = page.screenshot(type="png")
            img = Image.open(io.BytesIO(png)).convert("RGB")
            name = f"JOBS_{n:02d}.jpg"
            img.save(os.path.join(OUT, name), "JPEG", quality=95, subsampling=0)
            files.append(name)
            n += 1
        browser.close()
    srv.shutdown()

    with zipfile.ZipFile(os.path.join(OUT, "slides.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(os.path.join(OUT, f), f)

    # MP4 for the TV: every slide shown for SLIDE_SECONDS, already rotated, plays on any TV (H.264).
    secs = int(cfg.get("video_seconds_per_slide", 15))
    video = os.path.join(OUT, "jobs-this-week.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", f"1/{secs}", "-i", os.path.join(OUT, "JOBS_%02d.jpg"),
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
        "-r", "25", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-t", str(secs * len(files)), video,
    ], check=True)
    with open(os.path.join(OUT, "info.json"), "w") as fh:
        json.dump({"made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "slides": len(files),
                   "seconds_per_slide": secs, "min_days_open": min_days}, fh)
    print(f"Made {len(files)} slides + jobs-this-week.mp4 ({len(files) * secs}s) in docs/usb/ "
          f"(every job stays open at least {min_days} more days)")


if __name__ == "__main__":
    sys.exit(main())
