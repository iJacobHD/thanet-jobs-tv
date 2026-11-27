# Thanet Jobs TV

A portrait (9:16) job board for a TV mounted on its side. It shows 4 jobs per slide, each with a QR code that opens the job advert, and it updates itself.

* **Where the jobs come from:** DWP Find a Job (Work Hub, jobs.service.gov.uk). Its terms allow reasonable automated copying as long as DWP is credited, and the display does credit it.
* **What gets shown:** jobs in Thanet that are still open, entry level, and **not self-employed**.
* **The button:** https://eastkentjobs.github.io/week.html has a yellow **Jobs for this week** button. It downloads an MP4 that shows 12 seconds per slide and is already turned 270° for the sideways TV. Every job in it stays open for at least the next 7 days. Copy it onto the USB stick and play it on repeat. `Update USB stick.bat` can do the copying for you.
* **How it updates:** every morning, GitHub collects jobs from several official job feeds, removes duplicates, filters them, and remakes the board, the slides and the MP4. Nobody has to run anything, and nothing touches Work Hub.
  * **Reed** (secret `REED_API_KEY`) has closing dates.
  * **Teaching Vacancies** (Department for Education) needs no key and has closing dates. It covers school support jobs like teaching assistants, cleaners and catering.
  * **NHS Jobs** needs no key and has closing dates. It covers GP receptionists, care homes, healthcare assistants and similar.
  * **Adzuna** (secrets `ADZUNA_APP_ID` + `ADZUNA_APP_KEY`, optional) pulls from lots of other job sites, but gives no closing dates. Only jobs posted in the last 10 days are used, and they're shown as "Posted …, apply soon".
  * **Apprenticeship board** (`apprenticeships.html`-style: `index.html?board=apprenticeships`, green design) with its own video `usb/apprenticeships-this-week.mp4` and its own button on the download page. It takes every apprenticeship in the area from all sources; apprenticeships skip the experience/qualification/pay rules because they are paid training by design.
  * **Find an apprenticeship** (GOV.UK, Department for Education): read from its public search pages (about 10 pages a day, no key needed). If a free Display advert API key is ever saved as the `FAA_API_KEY` secret, the official API is used instead.
  * **Employers' own careers sites** (list in `config.json` → `employers`):
    * Supermarkets: Morrisons, Asda, Tesco, Lidl, M&S, Co-op, Waitrose/John Lewis, Sainsbury's, Iceland / The Food Warehouse.
    * Westwood Cross and the retail parks: Boots, Primark, Next, TK Maxx / Homesense, B&M, The Range, Halfords, Wickes / Toolstation, Currys, JD Sports, Smyths Toys, Hobbycraft, Hotel Chocolat, Hollywood Bowl.
    * Food, pubs and hotels: McDonald's, Greggs, Costa Coffee, Wetherspoon, Harvester / Toby Carvery / Miller & Carter, Premier Inn / Beefeater / Brewers Fayre, Travelodge.
    * More food, pubs and care: KFC, PizzaExpress, Zizzi, Shepherd Neame pubs & hotels, Compass Group (school/hospital catering), OCS (cleaning), Care UK and Barchester care homes, Specsavers, Royal Mail, East Kent College Group.
    * Hospitals: 2gether Support Solutions (porters, domestics, catering at QEQM Margate, Kent & Canterbury, William Harvey) - NHS Trust jobs come through NHS Jobs.
    * Each site is read the way it publishes jobs: its sitemap and the job details built into each advert, its own job feed or public jobs API, or its search-results pages. Only adverts in our towns are opened, and the reader waits between requests as each site asks.
    * Where a site gives a closing date it is used. Where it gives none, the job shows as "Open on X careers · apply soon" and is re-checked every morning.
    * Not possible: Aldi (bot check), Dunelm (jobs only appear after accepting cookies), Pets at Home (search only works inside their page), Superdrug (adverts go via a third party; they already reach Reed), Vue and Nando's (their sites refuse automated visits), Deichmann (search form only), Elev8 (no careers site), Mitie (bot check; its adverts reach Reed).
  * If a feed is down, yesterday's jobs from that feed are kept.
* **Area:** anywhere within **90 minutes door to door from Thanet by public transport** (`commute` in `config.json`). Each town has a minutes figure: the average train time plus about 25 minutes to walk to the station, wait, and walk at the other end. Today that includes Thanet, Herne Bay, Whitstable, Canterbury, Faversham, Sandwich, Deal, Sittingbourne, Ashford and Dover. Folkestone (~93) and Medway (~95) are over the limit.
* **Expired jobs:** the web board drops a job on its closing day. The video only includes jobs open for 7+ more days (`usb_min_days_open` in config.json), so replacing it on the stick once a week is enough.

```
config.json                     what counts as Thanet, salary caps, blocked employers
scripts/update_jobs.py          fetch, filter and write docs/jobs.json
scripts/qr.py                   QR code maker (no extra libraries needed)
scripts/render_slides.py        makes the JPG slides and jobs-this-week.mp4
scripts/reed_source.py          fetches jobs from Reed's official API
Update USB stick.bat            double-click on a Windows PC to put the newest slides on the stick
docs/usb/                       the latest JPG slides + slides.zip (rewritten by the robot)
docs/index.html                 the TV display
docs/week.html                  the "Jobs for this week" button page
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
6. Your board is now live at `https://eastkentjobs.github.io/`.

## Using a USB stick (TV photo slideshow)

Each scheduled run also makes picture slides: `docs/usb/JOBS_01.jpg`, `JOBS_02.jpg` and so on. Each slide is 1920×1080 with the design already turned 270°, so the TV needs no rotation setting. Every QR code on every slide is checked to make sure it scans.

**Set up once:** open `update_usb.ps1` in Notepad and change the `$Site` line to your GitHub Pages address.

**To refresh the stick:**

1. Plug the stick into any Windows PC.
2. Double-click **Update USB stick.bat**. It downloads the newest slides, deletes the old `JOBS_*.jpg` files from the `JOBS` folder on the stick, and copies the new ones in. Nothing else on the stick is touched.
3. Put the stick back in the TV.
4. Open the TV's Photos/Media app and start a slideshow of the `JOBS` folder. Set it to repeat, with about 12 seconds per slide.

**Important:** pictures on a stick can't update themselves. To stop expired jobs showing, slides only include jobs that stay open for **at least 4 more days** from when they were made (`usb_min_days_open` in `config.json`). **Refresh the stick at least twice a week (e.g. Monday and Thursday)** and nothing on the TV will be past its closing date. If your TV shows the slides upside down, set `"usb_rotate": 90` in `config.json`.

## Put it on the TV (web page version)

Open the link full-screen on whatever drives the TV: the TV's own browser, a Fire TV Stick (Silk browser), a Chromecast with Google TV, or a mini PC.
On a Windows PC, use kiosk mode so it starts full-screen with no bars:
`chrome.exe --kiosk "https://eastkentjobs.github.io/"`

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

## Careers vs the TV board (added 27 Nov 2026)
- **TV board and videos**: entry-level jobs only (`docs/jobs.json`). Video capped at `video_max_pages` (35 pages, ~7 min); if there are more jobs, the best ones for newcomers are kept (no experience needed, close to Thanet, no licence, closing within 2 weeks).
- **Pathway careers side**: local jobs that were left off the board *only* because they need experience, qualifications or are senior go to `docs/careers.json`. Pathway shows them under "Where it can lead" on each sector page and on the "All jobs in East Kent" page. They never appear on the TV.
- **Health check**: `data/source_health.json` records the last day each source found jobs. Any source with nothing for 7+ days is listed in `docs/health.json` and shown as a warning on the download page.
