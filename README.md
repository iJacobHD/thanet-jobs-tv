# Thanet Jobs TV

A portrait (9:16) job board for a TV mounted on its side. It shows 4 jobs per slide, each with a QR code that opens the job advert, and it updates itself.

* **Where the jobs come from:** DWP Find a Job (Work Hub, jobs.service.gov.uk). Its terms allow reasonable automated copying as long as DWP is credited, and the display does credit it.
* **What gets shown:** jobs in Thanet that are still open, entry level, and **not self-employed**.
* **How it updates:** Work Hub blocks GitHub's servers, so a member of staff collects the jobs. On Work Hub they click the **Collect Thanet jobs** bookmark, then upload the saved file. That upload starts the robot, which filters the jobs, makes the QR codes, and rebuilds the web board and the USB slides in about 5 minutes. **Staff instructions:** https://ijacobhd.github.io/thanet-jobs-tv/staff.html
* **Expired jobs disappear automatically.** The web board checks closing dates on every slide. The robot also rebuilds the USB slides every morning, leaving out anything closing within 4 days.

```
config.json                     what counts as Thanet, salary caps, blocked employers
scripts/update_jobs.py          fetch, filter and write docs/jobs.json
scripts/qr.py                   QR code maker (no extra libraries needed)
scripts/render_slides.py        makes the JPG slides for the USB stick
Update USB stick.bat            double-click on a Windows PC to put the newest slides on the stick
docs/usb/                       the latest JPG slides + slides.zip (rewritten by the robot)
docs/index.html                 the TV display
docs/staff.html                 staff instructions + the Collect Thanet jobs bookmark
docs/collector.js               what the bookmark runs on Work Hub (read-only)
incoming/                       upload collected job files here (the robot removes them after use)
docs/jobs.json                  current jobs (rewritten by the robot)
data/report.txt                 every job checked and WHY it was kept or skipped
.github/workflows/update-jobs.yml   runs the updater every 3 hours
```

## Set up (about 10 minutes, free)

1. Make a free GitHub account and create a new **public** repository, e.g. `thanet-jobs-tv`.
2. Upload everything in this folder, keeping the folders as they are. Go to **Add file → Upload files** and drag the folder contents in.
   *Important:* the `.github` folder is hidden on some computers. Make sure it gets uploaded. If it doesn't, create the file `.github/workflows/update-jobs.yml` in GitHub and paste in its contents.
3. Go to **Settings → Actions → General → Workflow permissions** and pick **Read and write permissions**, then click Save.
4. Go to **Settings → Pages**. Under Source, pick **Deploy from a branch**, branch `main`, folder `/docs`, then Save.
5. Go to the **Actions** tab → **Update Thanet jobs** → **Run workflow**. The first run takes about 5 minutes.
6. Your board is now live at `https://ijacobhd.github.io/thanet-jobs-tv/`.

## Using a USB stick (TV photo slideshow)

Each scheduled run also makes picture slides: `docs/usb/JOBS_01.jpg`, `JOBS_02.jpg` and so on. Each slide is 1920×1080 with the design already turned 270°, so the TV needs no rotation setting. Every QR code on every slide is checked to make sure it scans.

**Set up once:** open `update_usb.ps1` in Notepad and change the `$Site` line to your GitHub Pages address.

**To refresh the stick:**

1. Plug the stick into any Windows PC.
2. Double-click **Update USB stick.bat**. It downloads the newest slides, deletes the old `JOBS_*.jpg` files from the `JOBS` folder on the stick, and copies the new ones in. Nothing else on the stick is touched.
3. Put the stick back in the TV.
4. Open the TV's Photos/Media app and start a slideshow of the `JOBS` folder. Set it to repeat, with about 15 seconds per slide.

**Important:** pictures on a stick can't update themselves. To stop expired jobs showing, slides only include jobs that stay open for **at least 4 more days** from when they were made (`usb_min_days_open` in `config.json`). **Refresh the stick at least twice a week (e.g. Monday and Thursday)** and nothing on the TV will be past its closing date. If your TV shows the slides upside down, set `"usb_rotate": 90` in `config.json`.

## Put it on the TV (web page version)

Open the link full-screen on whatever drives the TV: the TV's own browser, a Fire TV Stick (Silk browser), a Chromecast with Google TV, or a mini PC.
On a Windows PC, use kiosk mode so it starts full-screen with no bars:
`chrome.exe --kiosk "https://ijacobhd.github.io/thanet-jobs-tv/"`

**Leave the TV's own setting on normal (landscape).** The page rotates itself 270° by default. Settings go on the end of the link:

| Add to the link | What it does |
|---|---|
| `?rotate=90` | Use this if the picture comes out upside-down (TV turned the other way) |
| `?rotate=0` | No rotation, for checking it on a normal monitor or phone |
| `?seconds=20` | How long each slide stays up (default 15) |
| `?perpage=4` | Jobs per slide (default 4) |

Settings can be combined, e.g. `...?rotate=90&seconds=20`.

## Tuning what counts as "entry level"

The filters are in `scripts/update_jobs.py`:

* `SELF_EMPLOYED`: any match means the job is skipped.
* `EXPERIENCE` and `QUALIFICATION`: any match means skipped. Phrases like "No experience required" are removed from the text first, so they don't count as asking for experience.
* `SENIOR_TITLES`: manager, nurse, teacher, engineer and similar titles are skipped. Titles containing "trainee" or "apprentice" are always allowed.

The quick controls are in `config.json`:

* `extra_block_ids`: hide a specific job. The ID is the last part of the job's link.
* `extra_allow_ids`: force a job onto the board.
* `blocked_employers`: hide every job from an employer, e.g. app-based self-employed work.
* `hide_when_days_left_below`: `1` means a job disappears on its closing day.
* `max_annual_salary` and `nhs_max_annual_salary`: pay caps that catch senior or NHS Band 3+ roles.

After each run, open `data/report.txt` to see every job checked and the reason it was kept or skipped. Check it for the first week or two, because word-matching will sometimes get a job wrong.

## If something breaks

* **Board shows old jobs:** check the Actions tab for a red ❌. If the job site changed its layout, the updater stops and keeps the last good list. The TV still removes expired jobs either way.
* **GitHub emails that the schedule was disabled:** GitHub pauses scheduled jobs in quiet repositories. Open Actions and click **Enable workflow**.
* **The job site blocks GitHub's servers:** run `python scripts/update_jobs.py` on any PC with Python, using Windows Task Scheduler every few hours, then upload `docs/jobs.json`.
