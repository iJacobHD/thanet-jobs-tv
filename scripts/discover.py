"""
Discovery robot - runs every night.

Works through data/candidates.json (companies with jobs our sectors hire for most), works out which job
system each careers site uses, tests it, and switches it on (data/auto_employers.json) if it works.

The governor keeps the morning run safe:
  * it only adds companies while the company-site part of the morning run uses under 75% of its time limit
    (measured every morning in data/source_health.json);
  * companies that find nothing for 30 days, or fail 3 mornings running, are parked and re-tested in 30 days;
  * it never reads anything robots.txt forbids, and never re-checks a "can't read" site more than every 60-90 days.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.robotparser

import requests

sys.path.insert(0, os.path.dirname(__file__))
import sources  # noqa: E402
import platforms  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = sources.UA
CHEAP = set(platforms.MODES) | {"greenhouse"}           # one request a morning
COST = {"cheap": 8.0, "sitemap": 90.0}                  # estimated seconds a morning for a new source
MAX_AUTO = int(os.environ.get("MAX_AUTO_SOURCES", 300))
PROBES_PER_NIGHT = int(os.environ.get("PROBES_PER_NIGHT", 40))
NIGHT_MINUTES = float(os.environ.get("DISCOVERY_MINUTES", 25))
JOBLIKE = re.compile(r"/(?:jobs?|vacanc\w*|job-details|jobdetails|positions?|opportunit\w*|careers?/(?:job|vacanc)\w*)/", re.I)


def load(name, default):
    try:
        return json.load(open(os.path.join(DATA, name), encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(name, obj):
    with open(os.path.join(DATA, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)


def robots_for(url, s):
    p = urllib.parse.urlsplit(url)
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = s.get(f"{p.scheme}://{p.netloc}/robots.txt", timeout=20)
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
    except requests.RequestException:
        rp.parse([])
    return rp


def detect(text):
    for mode, pat in platforms.UNSUPPORTED:
        if re.search(pat, text, re.I):
            bad = mode
            break
    else:
        bad = None
    for mode, pat in platforms.DETECT:
        for slug in re.findall(pat, text, re.I):
            if slug.lower() not in platforms.NOISE_SLUGS:
                return mode, slug, None
    return None, None, bad


def try_sitemap(url, s, rp, places, log):
    """Careers sites that publish their adverts in a sitemap with Google-style JobPosting data."""
    p = urllib.parse.urlsplit(url)
    origin = f"{p.scheme}://{p.netloc}"
    maps = [m for m in (rp.site_maps() or []) if m.startswith(origin)] or [origin + "/sitemap.xml"]
    try:
        links = sources._sitemap_urls(s, origin, [m.replace(origin, "") for m in maps][:4])
    except Exception:
        return None
    jobs = [u for u in links if JOBLIKE.search(u) and rp.can_fetch(UA["User-Agent"], u)]
    if len(jobs) < 3:
        return None
    for u in jobs[:3]:
        time.sleep(2)
        try:
            t = s.get(u, timeout=30).text
        except requests.RequestException:
            continue
        if sources._jobposting(t):
            seg = re.search(r"/([^/]+)/", urllib.parse.urlsplit(u).path)
            path = f"/{seg.group(1)}/" if seg else "/jobs?/"
            return {"mode": "all", "base": origin, "sitemaps": [m.replace(origin, "") for m in maps][:4],
                    "job_path": re.escape(path), "max_new_pages_per_run": 60,
                    "crawl_delay": max(2, int(rp.crawl_delay(UA["User-Agent"]) or 2))}
    return None


SEEN = {}   # careers site -> outside job-system domains spotted on it (to know which readers to build next)
JOBSYS = re.compile(r"job|career|recruit|vacanc|apply|talent|hire|ats|eploy|tribepad|harri|oleeo|cezanne|networx|jobtrain|hireful|kallidus", re.I)


def note_domains(name, base_url, text):
    home = urllib.parse.urlsplit(base_url).netloc.replace("www.", "")
    for u in re.findall(r'(?:href|src|action)="(https?://[^"]+)"', text):
        d = urllib.parse.urlsplit(u).netloc.lower().replace("www.", "")
        if d and home not in d and JOBSYS.search(d + urllib.parse.urlsplit(u).path):
            SEEN.setdefault(name, set()).add(d)


def probe(c, places, today, log):
    """Returns (status, emp_config or None)."""
    s = sources._session()
    url = c["careers"]
    rp = robots_for(url, s)
    if not rp.can_fetch(UA["User-Agent"], url):
        return "blocked by robots.txt", None
    mode, slug, bad = detect(url)
    if not mode:
        try:
            r = s.get(url, timeout=30)
            text = r.url + " " + r.text
        except requests.RequestException as e:
            return f"error: {type(e).__name__}", None
        mode, slug, bad = detect(text)
        note_domains(c["name"], url, r.text)
        if not mode:      # look one click deeper: "current vacancies" / "search jobs" links on the same page
            for href in re.findall(r'href="([^"]+)"', r.text)[:400]:
                if re.search(r"vacanc|jobs|careers|join-us|work-for-us|opportunit", href, re.I):
                    full = urllib.parse.urljoin(r.url, href)
                    if full == r.url or not rp.can_fetch(UA["User-Agent"], full) and urllib.parse.urlsplit(full).netloc == urllib.parse.urlsplit(r.url).netloc:
                        continue
                    m2, s2, b2 = detect(full)
                    if not m2:
                        time.sleep(1)
                        try:
                            t2 = s.get(full, timeout=30)
                            m2, s2, b2 = detect(t2.url + " " + t2.text)
                            note_domains(c["name"], url, t2.url + '"' + t2.text)
                            if urllib.parse.urlsplit(t2.url).netloc != urllib.parse.urlsplit(url).netloc:
                                SEEN.setdefault(c["name"], set()).add(urllib.parse.urlsplit(t2.url).netloc.lower())
                        except requests.RequestException:
                            continue
                    bad = bad or b2
                    if m2:
                        mode, slug = m2, s2
                        break
    if mode:
        emp = {"name": c["name"], "mode": mode, "board" if mode == "greenhouse" else "slug": slug}
        if mode == "lever" and "eu.lever" in url:
            emp["eu"] = True
        try:
            jobs = sources.employer_site(emp, places, today, {}, log=log)
        except Exception as e:
            return f"{mode} found but failed: {type(e).__name__}", None
        return f"ok: {mode} ({len(jobs)} local now)", emp
    if bad:
        return f"can't read: {bad}", None
    emp = try_sitemap(url, s, rp, places, log)
    if emp:
        emp["name"] = c["name"]
        return "ok: sitemap", emp
    return "no readable job feed", None


def main():
    today = dt.date.today()
    cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    places = cfg["allowed_places"]
    cands = load("candidates.json", [])
    state = load("discovery.json", {})
    auto = load("auto_employers.json", [])
    health = load("source_health.json", {})
    manual = {e["name"] for e in cfg.get("employers", [])}
    by_name = {e["name"]: e for e in auto}
    log = lambda m: print("   " + m)

    # 1. park auto sources that aren't earning their place
    for e in auto:
        h = health.get(e["name"]) or {}
        if not e.get("enabled", True):
            continue
        added = dt.date.fromisoformat(e.get("added", str(today)))
        last = h.get("last_found") or ""
        if h.get("fail_streak", 0) >= 3:
            why = "failed 3 mornings running"
        elif (today - added).days >= 30 and (not last or (today - dt.date.fromisoformat(last)).days >= 30):
            why = "no local jobs for 30 days"
        else:
            continue
        e["enabled"] = False
        state.setdefault(e["name"], {}).update(status=f"parked: {why}", next_check=str(today + dt.timedelta(days=30)))
        print(f"Parked {e['name']}: {why}")

    # 2. governor: how much of the morning time limit company sites use now
    limit = 0.75 * float(os.environ.get("EMPLOYER_MINUTES", 70)) * 60
    active = [e for e in cfg.get("employers", []) if e.get("enabled", True)] + [e for e in auto if e.get("enabled", True)]
    # measured seconds from the latest morning run; sources not measured yet count as a typical 30s (8s for feeds)
    used = sum((health.get(e["name"]) or {}).get("secs", COST["cheap"] if e.get("mode") in CHEAP else 30.0) for e in active)
    print(f"Governor: company sites use ~{used / 60:.0f} of {limit / 60:.0f} allowed minutes; {sum(1 for e in auto if e.get('enabled', True))} auto sources on")

    # 3. probe candidates that are due (never checked first, then parked/failed ones whose re-check date has passed)
    due = [c for c in cands if c["name"] not in manual and
           (c["name"] not in state or state[c["name"]].get("next_check", "") <= str(today))
           and not (by_name.get(c["name"]) or {}).get("enabled", False)]
    due.sort(key=lambda c: (c["name"] in state, state.get(c["name"], {}).get("checked", "")))
    stop = time.time() + NIGHT_MINUTES * 60
    probed = added = 0
    for c in due[:PROBES_PER_NIGHT]:
        if time.time() > stop:
            break
        print(f"- {c['name']} ({c.get('sector', '')}) {c['careers']}")
        try:
            status, emp = probe(c, places, today, log)
        except Exception as e:      # one bad site never stops the night
            status, emp = f"error: {type(e).__name__}", None
        probed += 1
        print(f"   -> {status}")
        # "no readable feed" is retried in 14 days: new readers get added for the job systems seen most often
        days = 7 if status.startswith("error") else 14 if status.startswith("no readable") else 90 if status.startswith(("can't", "blocked")) else 30
        st = {"status": status, "checked": str(today), "sector": c.get("sector", ""), "careers": c["careers"],
              "next_check": str(today + dt.timedelta(days=days)), "seen": sorted(SEEN.get(c["name"], []))[:12]}
        if emp:
            cost = COST["cheap"] if emp["mode"] in CHEAP else COST["sitemap"]
            if used + cost > limit or sum(1 for e in auto if e.get("enabled", True)) >= MAX_AUTO:
                st["status"] = status + " - waiting: time limit reached"
                st["next_check"] = str(today + dt.timedelta(days=7))
            else:
                emp.update(enabled=True, auto=True, sector=c.get("sector", ""), added=str(today))
                if c["name"] in by_name:
                    by_name[c["name"]].update(emp)
                else:
                    auto.append(emp); by_name[c["name"]] = emp
                used += cost
                added += 1
                st["status"] = status + " - added"
        state[c["name"]] = st
        time.sleep(1)

    save("discovery.json", state)
    save("auto_employers.json", auto)
    on = [e for e in auto if e.get("enabled", True)]
    summary = {"checked": str(today), "manual_sources": len(manual), "auto_sources": len(on),
               "parked": sum(1 for e in auto if not e.get("enabled", True)), "candidates": len(cands),
               "still_to_check": sum(1 for c in cands if c["name"] not in state and c["name"] not in manual),
               "time_used_pct": round(100 * used / (float(os.environ.get("EMPLOYER_MINUTES", 70)) * 60)),
               "probed_tonight": probed, "added_tonight": added,
               "by_sector": {sec: sum(1 for e in on if e.get("sector") == sec) for sec in sorted({e.get("sector", "") for e in on})},
               # job systems we can't read yet, most common first - the next readers to build
               "unread_systems": __import__("collections").Counter(d for v in state.values() if v.get("status", "").startswith("no readable")
                                                                  for d in v.get("seen", [])).most_common(20)}
    with open(os.path.join(ROOT, "docs", "sources.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
