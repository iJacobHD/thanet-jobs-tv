"""
Extra official job feeds. Each returns job dicts in the shape the filters use:
id, title, employer, pay, hours, location, job_type, posted, closing, description, url, source
(+ optional closing_estimated=True when the feed gives no closing date).

  * Teaching Vacancies (Department for Education) - open JSON API, no key, has closing dates.
  * NHS Jobs - public XML search feed, no key, has closing dates.
  * Adzuna - aggregator of many UK job sites; needs ADZUNA_APP_ID / ADZUNA_APP_KEY.
    No closing dates, so only recently posted jobs are used and they are labelled as such.
"""
import datetime as dt
import html
import re
import time
import xml.etree.ElementTree as ET

import requests

UA = {"User-Agent": "ThanetJobsTV/1.0 (community job board; daily)"}


def _text(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(h or "")))).strip()


def _date(s):
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(s or ""))
    return dt.date.fromisoformat(m.group(1)) if m else None


def _thanet(text, places):
    return bool(re.search(r"\b(?:" + "|".join(re.escape(p) for p in places) + r")\b", text or "", re.I))


# --------------------------------------------------------------------------- Teaching Vacancies
def teaching_vacancies(places, log=print, delay=0.3):
    s = requests.Session()
    s.headers.update(UA)
    jobs, url, pages = [], "https://teaching-vacancies.service.gov.uk/api/v1/jobs.json?page=1", 0
    while url and pages < 200:
        r = s.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        pages += 1
        for v in data.get("data", []):
            addr = ((v.get("jobLocation") or {}).get("address") or {})
            if isinstance(v.get("jobLocation"), list):
                addr = (v["jobLocation"][0] or {}).get("address") or {}
            loc = f"{addr.get('addressLocality', '')}, {addr.get('postalCode', '')}"
            if not _thanet(loc, places):
                continue
            sal = ((v.get("baseSalary") or {}).get("value") or {})
            unit = str(sal.get("unitText", "")).upper()
            pay = str(sal.get("value", ""))
            if pay and "£" in pay and unit == "HOUR":
                pay += " an hour"
            elif pay and "£" in pay and "year" not in pay.lower():
                pay += " a year"
            et = v.get("employmentType") or []
            et = et if isinstance(et, list) else [et]
            hours = "Full-time" if et == ["FULL_TIME"] else "Part-time" if et == ["PART_TIME"] else ("Full or part-time" if et else "")
            jobs.append({
                "id": "tv:" + v.get("url", "").rstrip("/").split("/")[-1][-36:],
                "title": _text(v.get("title")),
                "employer": _text((v.get("hiringOrganization") or {}).get("name")),
                "pay": pay, "hours": hours, "location": loc,
                "job_type": "", "posted": str(_date(v.get("datePosted")) or ""),
                "closing": str(_date(v.get("validThrough")) or ""),
                "description": _text(v.get("description"))[:12000],
                "closed_notice": False, "url": v.get("url", ""), "source": "Teaching Vacancies",
            })
        url = (data.get("links") or {}).get("next")
        time.sleep(delay)
    log(f"Teaching Vacancies: {len(jobs)} Thanet jobs (read {pages} pages)")
    return jobs


# --------------------------------------------------------------------------- NHS Jobs
def nhs_jobs(places, location="Margate", miles=10, log=print, delay=0.3):
    s = requests.Session()
    s.headers.update(UA)
    jobs, page, total_pages = [], 1, 1
    while page <= total_pages and page <= 50:
        r = s.get("https://www.jobs.nhs.uk/api/v1/search_xml",
                  params={"location": location, "distance": miles, "page": page}, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        total_pages = int(root.findtext("totalPages") or 1)
        for v in root.findall("vacancyDetails"):
            locs = [l.text or "" for l in v.findall("locations/location")]
            loc = next((l for l in locs if _thanet(l, places)), "")
            if not loc:
                continue
            sal = v.findtext("salary") or ""
            if re.fullmatch(r"£\s*\d+(?:\.\d+)?", sal.strip()) and float(sal.strip("£ ")) < 100:
                sal += " an hour"
            jobs.append({
                "id": "nhs:" + (v.findtext("id") or v.findtext("reference") or ""),
                "title": _text(v.findtext("title")),
                "employer": _text(v.findtext("employer")),
                "pay": sal, "hours": "", "location": loc,
                "job_type": v.findtext("type") or "",
                "posted": str(_date(v.findtext("postDate")) or ""),
                "closing": str(_date(v.findtext("closeDate")) or ""),
                "description": _text(v.findtext("description")),
                "closed_notice": False, "url": v.findtext("url") or "", "source": "NHS Jobs",
            })
        page += 1
        time.sleep(delay)
    log(f"NHS Jobs: {len(jobs)} Thanet jobs")
    return jobs


# --------------------------------------------------------------------------- Adzuna
def adzuna(app_id, app_key, places, location="Margate", km=16, max_days_old=10, show_days=21, log=print, delay=0.5):
    s = requests.Session()
    s.headers.update(UA)
    jobs, page = [], 1
    while page <= 10:
        r = s.get(f"https://api.adzuna.com/v1/api/jobs/gb/search/{page}", params={
            "app_id": app_id, "app_key": app_key, "where": location, "distance": km,
            "max_days_old": max_days_old, "results_per_page": 50, "content-type": "application/json"}, timeout=30)
        r.raise_for_status()
        data = r.json()
        res = data.get("results", [])
        for v in res:
            loc = (v.get("location") or {}).get("display_name", "")
            area = " ".join((v.get("location") or {}).get("area") or [])
            if not _thanet(f"{loc} {area}", places):
                continue
            created = _date(v.get("created"))
            if not created:
                continue
            lo, hi = v.get("salary_min"), v.get("salary_max")
            pay = ""
            if lo and not str(v.get("salary_is_predicted", "0")) == "1":
                per = "an hour" if lo < 100 else "a year"
                pay = f"£{lo:.2f} to £{(hi or lo):.2f} {per}" if lo < 100 else f"£{lo:,.0f} to £{(hi or lo):,.0f} {per}"
            ct = str(v.get("contract_time") or "").replace("_", "-")
            jobs.append({
                "id": "adz:" + str(v.get("id")),
                "title": _text(v.get("title")),
                "employer": _text((v.get("company") or {}).get("display_name")),
                "pay": pay, "hours": ct.capitalize() if ct else "", "location": loc,
                "job_type": str(v.get("contract_type") or "").title(),
                "posted": str(created),
                # No closing date from Adzuna: show for a limited time after posting, labelled as such.
                "closing": str(created + dt.timedelta(days=show_days)),
                "closing_estimated": True,
                "description": _text(v.get("description")),
                "closed_notice": False, "url": v.get("redirect_url", ""), "source": "Adzuna",
            })
        if len(res) < 50:
            break
        page += 1
        time.sleep(delay)
    log(f"Adzuna: {len(jobs)} Thanet jobs posted in the last {max_days_old} days")
    return jobs


# --------------------------------------------------------------------------- Employer careers sites
def _sitemap_urls(s, base, sitemaps, sitemap_filter=None, depth=0):
    out = []
    for sm in sitemaps:
        url = sm if sm.startswith("http") else base + sm
        try:
            r = s.get(url, timeout=40)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)
        if "<sitemapindex" in r.text and depth < 2:
            kids = [l for l in locs if not sitemap_filter or re.search(sitemap_filter, l)]
            out += _sitemap_urls(s, base, kids, sitemap_filter, depth + 1)
        else:
            out += locs
    return out


def _jobposting(html_text):
    import json as _json
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>([\s\S]*?)</script>', html_text):
        try:
            data = _json.loads(block)
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for d in items:
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                return d
    return None


def _from_text(html_text):
    """Fallback for sites without structured data (e.g. Sainsbury's): read title/location/pay from the page text."""
    h1 = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html_text)
    body = _text(re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html_text))
    loc = re.search(r"([A-Z][\w'&.() -]{2,60}, [A-Z][\w' -]{2,40}, [A-Z]{1,2}\d{1,2}[A-Z]? ?\d[A-Z]{2})", body)
    pay = re.search(r"£\s?\d+(?:\.\d{2})?\s*(?:per hour|an hour|p/?h)", body, re.I)
    hrs = re.search(r"\b(Part time|Full time)\b", body, re.I)
    if not (h1 and loc):
        return None
    return {"title": _text(h1.group(1)), "description": body[:12000],
            "jobLocation": {"address": {"addressLocality": loc.group(1)}},
            "baseSalary": {"value": {"value": pay.group(0) if pay else ""}},
            "employmentType": (hrs.group(1).upper().replace(" ", "_") if hrs else "")}


def employer_site(emp, places, today, cache, log=print):
    """
    Reads an employer's own careers site:
      mode "slug"           - sitemap job links whose web address names one of our towns (Morrisons, Asda, Tesco, Lidl, M&S)
      mode "all"            - every job link in the sitemap, remembered in a cache so each advert is read once (Boots, Waitrose, Sainsbury's)
      mode "location_pages" - the site's own town pages for our towns, then the jobs listed on them (Co-op)
    Each advert's structured JobPosting data (what Google Jobs reads) gives title, location, pay and any closing date.
    Respects the site's crawl-delay and only reads public pages that robots.txt allows.
    """
    s = requests.Session()
    s.headers.update(UA)
    base = emp["base"].rstrip("/")
    delay = float(emp.get("crawl_delay", 2))
    mode = emp.get("mode", "slug")
    towns = [p.lower().replace(" ", "-").replace(".", "").replace("'", "") for p in places if not re.fullmatch(r"[A-Z]{1,2}\d+", p)]
    town_re = re.compile(r"(?:^|[-/_])(?:" + "|".join(map(re.escape, towns)) + r")(?:[-/_.]|$)", re.I)
    urls = _sitemap_urls(s, base, emp.get("sitemaps", ["/sitemap.xml"]), emp.get("sitemap_filter"))
    if emp.get("url_rewrite"):
        a, b = emp["url_rewrite"]
        urls = [u.replace(a, b) for u in urls]
    urls = list(dict.fromkeys(urls))

    if mode == "location_pages":
        pages = [u for u in urls if re.search(emp["location_path"], u) and town_re.search(u.lower())]
        job_urls = []
        for pg in pages:
            time.sleep(delay)
            try:
                t = s.get(pg, timeout=30).text
            except requests.RequestException:
                continue
            for href in re.findall(r'href="([^"]+)"', t):
                if re.search(emp["job_link"], href):
                    job_urls.append(href if href.startswith("http") else base + href)
        job_urls = list(dict.fromkeys(job_urls))
    else:
        job_urls = [u for u in urls if re.search(emp.get("job_path", "/jobs?/"), u)]
        if mode == "slug":
            job_urls = [u for u in job_urls if town_re.search(u.lower())]

    ecache = cache.setdefault(emp["name"], {})
    for k in list(ecache):            # forget adverts that are no longer listed
        if k not in job_urls:
            del ecache[k]
    log(f"{emp['name']}: {len(urls)} links in sitemap, {len(job_urls)} adverts to consider")

    jobs, opened, budget = [], 0, int(emp.get("max_new_pages_per_run", 400))
    for u in job_urls:
        c = ecache.get(u)
        if c and not c.get("local"):
            continue                                   # read before, not in our area
        if not c and opened >= budget:
            continue                                   # rest will be read on later runs
        time.sleep(delay)
        opened += 1
        try:
            r = s.get(u, timeout=30)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        post = _jobposting(r.text) or (_from_text(r.text) if emp.get("text_fallback") else None)
        if not post:
            ecache[u] = {"local": False, "checked": str(today)}
            continue
        loc_obj = post.get("jobLocation") or {}
        if isinstance(loc_obj, list):
            loc_obj = loc_obj[0] if loc_obj else {}
        addr = loc_obj.get("address") or {}
        if isinstance(addr, str):
            addr = {"addressLocality": addr}
        loc = ", ".join(x for x in [addr.get("streetAddress") if emp.get("use_street") else "", addr.get("addressLocality") or "", addr.get("postalCode") or ""] if x)
        local = _thanet(loc, places) or (mode != "all" and _thanet(u.replace("-", " "), places))
        ecache[u] = {"local": bool(local), "checked": str(today)}
        if not local:
            continue
        sal = ((post.get("baseSalary") or {}).get("value") or {})
        pay = ""
        if isinstance(sal, dict):
            v = sal.get("value") or sal.get("minValue") or ""
            hi = sal.get("maxValue")
            unit = str(sal.get("unitText", "")).upper()
            if v and "£" in str(v):
                pay = str(v)
            elif v:
                pay = f"£{v}" + (f" to £{hi}" if hi else "") + (" an hour" if unit == "HOUR" else " a year" if unit == "YEAR" else "")
        et = post.get("employmentType") or ""
        et = et[0] if isinstance(et, list) and et else et
        closing = _date(post.get("validThrough"))
        ident = (post.get("identifier") or {}).get("value") if isinstance(post.get("identifier"), dict) else None
        job = {
            "id": f"emp:{emp['name'].lower()}:" + str(ident or re.sub(r"\W+", "", u[-40:])),
            "title": _text(post.get("title")),
            "employer": emp["name"],
            "pay": pay,
            "hours": {"FULL_TIME": "Full-time", "PART_TIME": "Part-time"}.get(str(et).upper(), ""),
            "location": loc or u, "job_type": "",
            "posted": str(_date(post.get("datePosted")) or ""),
            "description": _text(post.get("description"))[:12000],
            "closed_notice": False, "url": u, "source": emp["name"],
        }
        if closing:
            job["closing"] = str(closing)
        else:   # listed on their site today but no closing date published: re-checked every morning
            job["closing"] = str(today + dt.timedelta(days=int(emp.get("show_days_without_closing", 8))))
            job["closing_estimated"] = True
            job["listed_only"] = True
        jobs.append(job)
    left = sum(1 for u in job_urls if u not in ecache)
    log(f"{emp['name']}: opened {opened} adverts, {len(jobs)} local jobs" + (f", {left} still to read on later runs" if left else ""))
    return jobs
