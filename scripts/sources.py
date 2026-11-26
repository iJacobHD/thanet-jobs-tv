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
# Reading careers sites stops opening NEW adverts after this many minutes, so the daily run always finishes
# well inside GitHub's time limit. Anything left is read on the next morning's run (the cache remembers progress).
DEADLINE = time.time() + 60 * float(__import__("os").environ.get("EMPLOYER_MINUTES", "70"))


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
    mode = emp.get("mode", "slug")
    if mode in SPECIAL_MODES:
        return SPECIAL_MODES[mode](emp, places, today, cache, log)
    s = requests.Session()
    s.headers.update(UA)
    base = emp["base"].rstrip("/")
    delay = float(emp.get("crawl_delay", 2))
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
        if emp.get("url_geo_box"):        # links that carry @lat,lng (McDonald's): keep the ones near Thanet
            la1, la2, lo1, lo2 = emp["url_geo_box"]
            def _in(u):
                m = re.search(r"@(-?[\d.]+),(-?[\d.]+)", u)
                return bool(m) and la1 <= float(m.group(1)) <= la2 and lo1 <= float(m.group(2)) <= lo2
            job_urls = [u for u in job_urls if _in(u)]

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
        if not c and (opened >= budget or time.time() > DEADLINE):
            continue                                   # rest will be read on later runs
        time.sleep(delay)
        opened += 1
        try:
            r = s.get(u, timeout=30)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        if _expired(r.text):
            ecache[u] = {"local": False, "checked": str(today)}
            continue
        post = (_jobposting(r.text) or _microdata(r.text)
                or (_fields(r.text) if emp.get("fields") else None)
                or (_from_text(r.text) if emp.get("text_fallback") else None))
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
        closing = _date(post.get("validThrough")) or _anydate(post.get("validThrough"))
        ident = (post.get("identifier") or {}).get("value") if isinstance(post.get("identifier"), dict) else None
        job = {
            "id": f"emp:{emp['name'].lower()}:" + str(ident or re.sub(r"\W+", "", u[-40:])),
            "title": _text(post.get("title")),
            "employer": emp["name"],
            "pay": pay,
            "hours": {"FULL_TIME": "Full-time", "PART_TIME": "Part-time"}.get(str(et).upper(), ""),
            "location": loc or u, "job_type": "",
            "posted": str(_date(post.get("datePosted")) or _anydate(post.get("datePosted")) or ""),
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


# --------------------------------------------------------------------------- page helpers for careers sites
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
EXPIRED = re.compile(r"(vacancy (?:has now expired|is now closed|has closed)|deadline for this vacancy has now passed|"
                     r"no longer accepting applications|this job (?:is no longer available|has expired)|position has been filled|"
                     r"open to internal (?:applications|applicants|candidates) (?:from existing [\w ]+ )?only|internal (?:applicants|applications|candidates) only)", re.I)


def _expired(html_text):
    return bool(EXPIRED.search(_text(re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html_text or ""))[:20000]))


def _anydate(s):
    """Dates written for people: '17 December, 2026', '10 Dec 2026', 'Tue Dec 01 00:00:00 UTC 2026', '01/12/2026'."""
    s = str(s or "")
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*,?\s+(\d{4})", s)
    if m and m.group(2).lower() in MONTHS:
        d, mo, y = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
    else:
        m = re.search(r"\b([A-Za-z]{3})[a-z]*\s+(\d{1,2})\b.*?\b(\d{4})\b", s)
        if m and m.group(1).lower() in MONTHS:
            d, mo, y = int(m.group(2)), MONTHS[m.group(1).lower()], int(m.group(3))
        else:
            m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", s)
            if not m:
                return None
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def _microdata(html_text):
    """schema.org JobPosting written as itemprop attributes (SuccessFactors sites such as Currys)."""
    if 'itemtype="http://schema.org/JobPosting"' not in html_text and "schema.org/JobPosting" not in html_text:
        return None
    def prop(name):
        m = re.search(r'itemprop="%s"[^>]*?content="([^"]*)"' % name, html_text) or \
            re.search(r'itemprop="%s"[^>]*>([\s\S]{0,300}?)</' % name, html_text)
        return _text(m.group(1)) if m else ""
    title = (prop("title")
             or _text((re.search(r'data-careersite-propertyid="title"[^>]*>([\s\S]{0,200}?)</', html_text) or [None, ""])[1])
             or _text((re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html_text) or [None, ""])[1])
             or re.split(r"\s+(?:Job Details|\||-)\s+", _text((re.search(r"<title>([\s\S]*?)</title>", html_text) or [None, ""])[1]))[0])
    loc = " ".join(x for x in [prop("streetAddress"), prop("addressLocality"), prop("addressRegion"), prop("postalCode")] if x)
    if not (title and loc):
        return None
    return {"title": title, "description": prop("description")[:12000] or _text(html_text)[:12000],
            "jobLocation": {"address": {"addressLocality": loc}},
            "validThrough": prop("validThrough"), "datePosted": prop("datePosted"),
            "employmentType": prop("employmentType")}


def _fields(html_text):
    """Labelled fields on the page instead of structured data:
       Eploy sites (B&M, Travelodge, Wetherspoon) and Premier Inn ('Location: Margate, United Kingdom')."""
    body = _text(re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html_text))
    t = _text((re.search(r"<title>([\s\S]*?)</title>", html_text) or [None, ""])[1])
    h1 = _text((re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html_text) or [None, ""])[1])
    title = h1 if 2 < len(h1) < 100 else re.split(r"\s+(?:-|\|)\s+", t)[0]
    title = re.sub(r"\s+in\s+[A-Z][\w' .-]+$", "", title)
    loc = None
    for pat in (r"\bLocation:?\s*([A-Z][^:]{1,60}?)\s+(?:Location is a required|Salary|Pay\b|Position|Vacancy Type|Date Posted|Closing)",
                r"All locations\s+([A-Z][^:]{1,60}?)\s+All locations is a required",
                r"\bLocation:\s*([^:]{2,60}?,\s*United Kingdom)",
                r"LOCATION:\s*([^:]{4,120}?[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2})"):
        rx = re.compile(pat)
        found = [m.group(1).strip() for m in (rx.match(body, i.start()) for i in re.finditer(r"Location|All locations|LOCATION", body)) if m]
        found = [x for x in found if not re.search(r"\b(?:Search|Location|Keywords|Careers)\b", x)] or found
        if found:
            loc = min(found, key=len)
            break
    if not loc:
        m = re.search(r"\sin\s+([A-Z][\w' .-]{2,40}?)\s+(?:-|\|)\s+", t)
        loc = m.group(1) if m else None
    if not (title and loc):
        return None
    pay = re.search(r"(?:Salary|Pay):?\s*(£[^A-Z]{1,60}?)(?=\s+[A-Z])", body)
    pay = pay.group(1).strip() if pay else ""
    if not pay:
        m = re.search(r"Salary details:\s*£?(\d{1,2}\.\d{2})\b", body)
        pay = f"£{m.group(1)} an hour" if m else _pay_in_text(body)
    close = re.search(r"(?:Closing|Close) [Dd]ate:?\s*([^A-Z]{0,3}\d{1,2}\s+\w+\s+\d{4})", body)
    posted = re.search(r"(?:Date Posted|Posted on):?\s*(\d{1,2}\s+\w+\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})", body)
    vt = re.search(r"(?:Vacancy Type|Vacancy type):?\s*(Full|Part)[ -]?[Tt]ime", body)
    return {"title": title, "description": body[:12000],
            "jobLocation": {"address": {"addressLocality": loc}},
            "baseSalary": {"value": {"value": pay}},
            "validThrough": str(_anydate(close.group(1))) if close else "",
            "datePosted": str(_anydate(posted.group(1))) if posted else "",
            "employmentType": (vt.group(1).upper() + "_TIME") if vt else ""}


def _closing_in_text(text):
    m = re.search(r"(?:Apply by|Closing date|Closing Date:|Applications close:?|Application deadline:?|Closes:?)\s*"
                  r"((?:[A-Za-z]{3,9},?\s+)?\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})", text)
    return _anydate(m.group(1)) if m else None


def _pay_in_text(text):
    m = re.search(r"£\s?\d[\d,]*(?:\.\d{2})?(?:\s*(?:-|to|–)\s*£?\s?\d[\d,]*(?:\.\d{2})?)?\s*(?:per hour|an hour|p/?h|per annum|a year|pa\b)", text, re.I)
    return m.group(0) if m else ""


def _job(emp, ident, title, location, url, today, pay="", hours="", closing=None, posted="", description=""):
    j = {"id": f"emp:{emp['name'].lower()}:{ident}", "title": _text(title), "employer": emp.get("employer", emp["name"]),
         "pay": pay or "", "hours": hours or "", "location": location, "job_type": "",
         "posted": str(posted or ""), "description": (description or "")[:12000], "closed_notice": False,
         "url": url, "source": emp["name"]}
    if closing:
        j["closing"] = str(closing)
    else:
        j["closing"] = str(today + dt.timedelta(days=int(emp.get("show_days_without_closing", 8))))
        j["closing_estimated"] = True
        j["listed_only"] = True
    return j


def _hours(text):
    t = (text or "").lower()
    return "Part-time" if "part" in t else "Full-time" if "full" in t else ""


def _session():
    s = requests.Session()
    s.headers.update(UA)
    return s


def _open_detail(s, emp, url, delay):
    """Open one local advert for its closing date / pay / description. Returns (closing, pay, text) or None if it says it has closed."""
    time.sleep(delay)
    try:
        r = s.get(url, timeout=30)
    except requests.RequestException:
        return (None, "", "")
    if r.status_code != 200:
        return (None, "", "")
    if _expired(r.text):
        return None
    post = _jobposting(r.text) or _microdata(r.text)
    body = _text(re.sub(r"<(script|style)[\s\S]*?</\1>", " ", r.text))
    closing = (_date(post.get("validThrough")) if post else None) or _closing_in_text(body)
    desc = _text(post.get("description")) if post else body
    return (closing, _pay_in_text(body), desc)


# --------------------------------------------------------------------------- special careers-site readers
def listing_pages(emp, places, today, cache, log=print):
    """
    A careers site whose search-results pages list every vacancy with its location (Greggs, Halfords).
    Reads the listing pages, keeps rows that name one of our towns, then opens just those adverts
    for the closing date and pay.
    """
    s, base, delay = _session(), emp["base"].rstrip("/"), float(emp.get("crawl_delay", 2))
    link_re = re.compile(emp["job_link"])
    rows, seen = [], set()
    for page in range(1, int(emp.get("max_pages", 1)) + 1):
        if time.time() > DEADLINE:
            break
        url = base + emp["listing"].format(page=page)
        if page > 1:
            time.sleep(delay)
        try:
            t = s.get(url, timeout=40).text
        except requests.RequestException:
            break
        parts = re.split(r'(?=<a\b[^>]*href="[^"]*(?:%s))' % emp["job_link"], t)
        new = 0
        for part in parts[1:]:
            m = re.match(r'<a\b[^>]*href="([^"]+)"', part)
            if not m or not link_re.search(m.group(1)):
                continue
            href = m.group(1) if m.group(1).startswith("http") else base + m.group(1)
            if href in seen:
                continue
            seen.add(href)
            new += 1
            rows.append((href, part[:int(emp.get("row_chars", 1500))]))
        if not new:
            break
    jobs = []
    for href, row in rows:
        text = _text(row)
        if not _thanet(text, places) or re.search(r"internal only", text, re.I):
            continue
        title = _text((re.search(emp.get("title_re", r"<a\b[^>]*>([\s\S]*?)</a>"), row) or [None, ""])[1])
        loc = _text((re.search(emp["location_re"], row) or [None, text])[1]) if emp.get("location_re") else text
        closing = _closing_in_text(text)
        pay = _pay_in_text(text)
        desc = ""
        if emp.get("open_local", True):
            d = _open_detail(s, emp, href, delay)
            if d is None:
                continue
            closing = closing or d[0]
            pay = pay or d[1]
            desc = d[2]
        posted = _anydate((re.search(r"Posted on\s*(.{6,30})", text) or [None, ""])[1])
        ident = (re.findall(r"\d{3,}", href) or [re.sub(r"\W+", "", href[-40:])])[-1]
        jobs.append(_job(emp, ident, title, loc, href, today, pay=pay,
                         hours=_hours(text), closing=closing, posted=posted or "", description=desc))
    log(f"{emp['name']}: {len(rows)} adverts listed, {len(jobs)} local jobs")
    return jobs


def costa(emp, places, today, cache, log=print):
    """Costa Coffee careers site search (the same request its own search page makes)."""
    s, base = _session(), emp["base"].rstrip("/")
    jobs, page, pages = [], 0, 1
    while page < pages and page < 30:
        r = s.post(base + "/wp-json/posts/search", timeout=120,
                   data={"paginate[page]": page, "paginate[per_page]": 50, "status[]": "publish"})
        d = r.json()
        pages = int(d.get("total_pages") or 1)
        for x in d.get("results", []):
            loc = x.get("full_location") or ""
            if x.get("country") not in ("GB", "UK", None) or not _thanet(loc + " " + (x.get("postal_code") or ""), places):
                continue
            jobs.append(_job(emp, x.get("id"), x.get("post_title"), loc, x.get("permalink"), today,
                             hours="", posted=str(x.get("posted_at") or "")[:10],
                             description=x.get("employment_indicator") or ""))
        page += 1
        time.sleep(float(emp.get("crawl_delay", 2)))
    log(f"{emp['name']}: {len(jobs)} local jobs")
    return jobs


def phenom(emp, places, today, cache, log=print):
    """Phenom careers sites (TJX: TK Maxx / Homesense): the site's own keyword search, one search per town."""
    import json as _json
    s, base, delay = _session(), emp["base"].rstrip("/"), float(emp.get("crawl_delay", 3))
    towns = emp.get("search_towns") or ["Broadstairs", "Margate", "Ramsgate", "Canterbury", "Ashford", "Dover", "Deal", "Whitstable", "Herne Bay", "Sittingbourne", "Faversham"]
    jobs, seen = [], set()
    for town in towns:
        time.sleep(delay)
        try:
            t = s.get(base + emp.get("search_path", "/global/en/search-results"), params={"keywords": town}, timeout=40).text
        except requests.RequestException:
            continue
        i = t.find('"eagerLoadRefineSearch"')
        if i < 0:
            continue
        j = t.find('"jobs":[', i)
        if j < 0:
            continue
        try:
            arr, _ = _json.JSONDecoder().raw_decode(t[j + 7:])
        except ValueError:
            continue
        for x in arr:
            loc = x.get("address") or x.get("cityStateCountry") or ""
            if x.get("country") != emp.get("country", "United Kingdom") or not _thanet(loc + " " + (x.get("city") or ""), places):
                continue
            jid = x.get("jobId") or x.get("reqId")
            if jid in seen:
                continue
            seen.add(jid)
            url = f"{base}{emp.get('job_prefix', '/global/en/job/')}{jid}"
            jb = _job(emp, jid, x.get("title"), loc, url, today, hours=_hours(x.get("type")),
                      posted=str(x.get("postedDate") or "")[:10],
                      description=(x.get("ml_job_parser") or {}).get("descriptionTeaser") or x.get("descriptionTeaser") or "")
            if x.get("brand"):
                jb["employer"] = x["brand"]
            jobs.append(jb)
    log(f"{emp['name']}: {len(jobs)} local jobs")
    return jobs


def xml_feed(emp, places, today, cache, log=print):
    """An employer's own job feed in the standard Indeed XML format (The Range)."""
    s = _session()
    r = s.get(emp["feed"], timeout=60)
    root = ET.fromstring(r.content)
    jobs = []
    for x in root.iter("job"):
        g = lambda k: (x.findtext(k) or "").strip()
        loc = ", ".join(v for v in [g("streetaddress"), g("city"), g("postalcode")] if v)
        if not _thanet(loc, places):
            continue
        desc = _text(g("description"))
        jobs.append(_job(emp, g("referencenumber"), g("title"), loc, g("url").replace("&source=Indeed", ""), today,
                         pay=g("salary") or _pay_in_text(desc), hours=_hours(g("jobtype") or desc[:400]),
                         closing=_anydate(g("expirationdate")) if g("expirationdate") else None,
                         posted=str(_anydate(g("date")) or ""), description=desc))
    log(f"{emp['name']}: {len(jobs)} local jobs")
    return jobs


def greenhouse(emp, places, today, cache, log=print):
    """Greenhouse public job board API (JD Sports)."""
    s = _session()
    d = s.get(f"https://boards-api.greenhouse.io/v1/boards/{emp['board']}/jobs", params={"content": "true"}, timeout=60).json()
    jobs = []
    for x in d.get("jobs", []):
        loc = (x.get("location") or {}).get("name", "")
        if not _thanet(loc, places):
            continue
        desc = _text(html.unescape(x.get("content") or ""))
        jobs.append(_job(emp, x.get("id"), x.get("title"), loc, x.get("absolute_url"), today,
                         pay=_pay_in_text(desc), hours=_hours(x.get("title") + " " + desc[:300]),
                         closing=_date(x.get("application_deadline")), posted=str(x.get("first_published") or "")[:10],
                         description=desc))
    log(f"{emp['name']}: {len(d.get('jobs', []))} adverts, {len(jobs)} local jobs")
    return jobs


def aspnet_grid(emp, places, today, cache, log=print):
    """Kallidus/ASP.NET vacancy table with numbered pages (Iceland & The Food Warehouse)."""
    s, base, delay = _session(), emp["base"].rstrip("/"), float(emp.get("crawl_delay", 3))
    url = base + emp.get("listing", "/Search.aspx")
    r = s.get(url, timeout=40)
    t = r.text
    rows, page = [], 1
    while True:
        for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", t):
            m = re.search(r'href="[^"]*VacancyInformation\.aspx\?VId=(\d+)"[^>]*>([^<]+)</a>', tr)
            if m:
                cells = [_text(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr)]
                rows.append((m.group(1), _text(m.group(2)), " ".join(cells)))
        page += 1
        if page > int(emp.get("max_pages", 40)) or f"Page${page}" not in t:
            break
        form = dict(re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', t))
        target = re.search(r"__doPostBack\('([^']+)','Page\$%d'\)" % page, t)
        if not target:
            break
        form["__EVENTTARGET"] = html.unescape(target.group(1))
        form["__EVENTARGUMENT"] = f"Page${page}"
        time.sleep(delay)
        t = s.post(url, data={k: html.unescape(v) for k, v in form.items()}, timeout=40).text
    jobs, seen = [], set()
    for vid, title, rowtext in rows:
        if vid in seen or not _thanet(rowtext, places):
            continue
        seen.add(vid)
        href = f"{base}/VacancyInformation.aspx?VId={vid}"
        d = _open_detail(s, emp, href, delay)
        if d is None:
            continue
        loc = rowtext.replace(title, "").strip()
        jobs.append(_job(emp, vid, title, loc, href, today, pay=d[1], hours=_hours(d[2][:600]),
                         closing=d[0], description=d[2]))
    log(f"{emp['name']}: {len(rows)} adverts listed, {len(jobs)} local jobs")
    return jobs


def networx(emp, places, today, cache, log=print):
    """Networx 'current-vacancies.com' careers sites (Hobbycraft): the JSON list its own search page loads."""
    import json as _json
    s, base = _session(), emp["base"].rstrip("/")
    page = s.get(base + emp["page"], timeout=40).text
    token = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', page)
    data = {"ClientID": int(emp["client_id"]), "OnboardingPageID": int(emp.get("onboarding_page_id", 0)),
            "DynamicFields": [], "SearchResultFields": [], "CurrentPage": 1, "PageSearchResults": True,
            "SearchResultPageSize": 500, "keywords": "", "Locations": ["0"]}
    form = {"data": _json.dumps(data), "hdnNewWorld": "True"}
    if token:
        form["__RequestVerificationToken"] = token.group(1)
    d = s.post(base + "/Careers/SearchVacancies", data=form, timeout=60).json()
    jobs = []
    for x in d.get("Data", []):
        loc = ", ".join(v for v in [x.get("Location"), x.get("Postcode")] if v)
        if not _thanet(loc, places):
            continue
        desc = x.get("JobDescription") or ""
        jobs.append(_job(emp, x.get("VacancyID"), x.get("VacancyTitle"), loc, x.get("ApplyLink"), today,
                         pay=x.get("8383_Salary") or _pay_in_text(desc), hours=_hours(desc[:400]),
                         closing=_anydate(x.get("ExpiryDate")), posted=str(_anydate(x.get("CreatedDate")) or ""),
                         description=desc))
    log(f"{emp['name']}: {len(d.get('Data', []))} adverts, {len(jobs)} local jobs")
    return jobs


SPECIAL_MODES = {"networx": networx, "listing": listing_pages, "costa": costa, "phenom": phenom, "xml_feed": xml_feed,
                 "greenhouse": greenhouse, "aspnet_grid": aspnet_grid}


# --------------------------------------------------------------------------- Find an apprenticeship (GOV.UK)
def apprenticeships(api_key, places, centres=None, log=print, delay=0.5):
    """
    Official 'Display advert API' (v2) from Find an apprenticeship (Department for Education).
    Needs a free subscription key from developer.apprenticeships.education.gov.uk (secret FAA_API_KEY).
    Every advert has a real closing date. Searches around each centre and keeps adverts in our towns.
    """
    centres = centres or [("Margate", 51.389, 1.386, 25), ("Ashford", 51.146, 0.875, 10), ("Sittingbourne", 51.340, 0.734, 8)]
    s = _session()
    s.headers.update({"Ocp-Apim-Subscription-Key": api_key, "X-Version": "2"})
    url = "https://api.apprenticeships.education.gov.uk/vacancies/vacancy"
    jobs, seen = [], set()

    def g(d, *keys):
        for k in keys:
            if isinstance(d, dict):
                for kk in (k, k[:1].upper() + k[1:]):
                    if kk in d and d[kk] not in (None, ""):
                        return d[kk]
        return None

    for name, lat, lon, miles in centres:
        page, pages = 1, 1
        while page <= pages and page <= 20:
            r = s.get(url, params={"Lat": lat, "Lon": lon, "DistanceInMiles": miles, "PageNumber": page,
                                   "PageSize": 100, "Sort": "AgeDesc", "FilterBySubscription": "false"}, timeout=60)
            r.raise_for_status()
            d = r.json()
            pages = int(g(d, "totalPages") or 1)
            for v in g(d, "vacancies") or []:
                ref = str(g(v, "vacancyReference") or "")
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                addrs = g(v, "addresses") or ([g(v, "address")] if g(v, "address") else [])
                addr = addrs[0] if addrs else {}
                loc = ", ".join(str(x) for x in [g(addr, "addressLine1"), g(addr, "addressLine2"), g(addr, "addressLine3"),
                                                 g(addr, "addressLine4"), g(addr, "postcode")] if x)
                if not _thanet(loc, places):
                    continue
                w = g(v, "wage") or {}
                wt = str(g(w, "wageType") or "")
                amt = g(w, "wageAmount")
                if amt:
                    a = float(amt)
                    pay = f"£{a:,.0f} a year" if a > 1000 else f"£{a:.2f} an hour"
                elif "Apprentice" in wt:
                    pay = "Apprentice minimum wage"
                elif "NationalMinimum" in wt or "LivingWage" in wt:
                    pay = "National minimum wage or above"
                else:
                    pay = str(g(w, "wageAdditionalInformation") or "")
                hrs = g(v, "hoursPerWeek")
                desc = _text(" ".join(str(x) for x in [g(v, "description"), g(v, "outcomeDescription"),
                                                       g(w, "workingWeekDescription"), (g(v, "course") or {}).get("title") if isinstance(g(v, "course"), dict) else ""] if x))
                closing = _date(g(v, "closingDate"))
                jobs.append({
                    "id": "faa:" + ref, "title": _text(g(v, "title")), "employer": _text(g(v, "employerName")),
                    "pay": pay, "hours": "Part-time" if hrs and float(hrs) < 30 else "Full-time",
                    "location": loc, "job_type": "Apprenticeship", "posted": str(_date(g(v, "postedDate")) or ""),
                    "description": desc[:12000], "closed_notice": False,
                    "url": g(v, "vacancyUrl") or f"https://www.findapprenticeship.service.gov.uk/apprenticeship/{ref}",
                    "source": "Find an apprenticeship", "closing": str(closing) if closing else "",
                })
            page += 1
            time.sleep(delay)
    jobs = [j for j in jobs if j["closing"]]
    log(f"Find an apprenticeship: {len(jobs)} apprenticeships in our area")
    return jobs


def apprenticeships_site(places, centres=None, log=print, delay=2):
    """
    Find an apprenticeship (GOV.UK) without an API key: its own public search-results pages,
    which list title, employer, address, wage, closing date and posted date for every advert.
    About 10 page loads a day, 2 seconds apart.
    """
    centres = centres or [("Margate", 30), ("Ashford, Kent", 10), ("Sittingbourne", 8)]
    s = _session()
    base = "https://www.findapprenticeship.service.gov.uk"
    jobs, seen = [], set()
    for loc, miles in centres:
        for page in range(1, 31):
            try:
                r = s.get(base + "/apprenticeships", params={"location": loc, "distance": miles, "pageNumber": page}, timeout=40)
            except requests.RequestException:
                break
            if r.status_code != 200:
                break
            items = re.findall(r'<li class="das-search-results__list-item[\s\S]*?</li>', r.text)
            if not items:
                break
            for li in items:
                m = re.search(r'href="/apprenticeship/(VAC\d+)"', li)
                if not m or m.group(1) in seen:
                    continue
                ref = m.group(1)
                seen.add(ref)
                ps = [_text(x) for x in re.findall(r"<p[^>]*>([\s\S]*?)</p>", li)]
                title = _text((re.search(r'-vacancy-title">([\s\S]*?)</span>', li) or [None, ""])[1])
                employer = ps[0] if ps else ""
                address = ps[1] if len(ps) > 1 else ""
                field = lambda name: next((x[len(name):].strip() for x in ps if x.startswith(name)), "")
                closing = _anydate((re.search(r"Closes[^()]*\(([^)]+)\)", _text(li)) or [None, ""])[1]) \
                    or _anydate((re.search(r"Closes on ([^<]+)", _text(li)) or [None, ""])[1])
                posted = _anydate((re.search(r"Posted (?:on )?(\d{1,2} \w+ \d{4})", _text(li)) or [None, ""])[1])
                if not _thanet(address, places) or not closing:
                    continue
                jobs.append({
                    "id": "faa:" + ref, "title": title, "employer": employer,
                    "pay": field("Wage"), "hours": "", "location": address, "job_type": "Apprenticeship",
                    "posted": str(posted or ""), "description": "Training course: " + field("Training course"),
                    "closed_notice": False, "url": f"{base}/apprenticeship/{ref}",
                    "source": "Find an apprenticeship", "closing": str(closing),
                })
            if f"pageNumber={page + 1}" not in r.text:
                break
            time.sleep(delay)
    log(f"Find an apprenticeship (website): {len(jobs)} apprenticeships in our area")
    return jobs


# Ordnance Survey grid (hectometres) of our towns - for sites that give a map position instead of a town
OS_TOWNS = {"Margate": (6355, 1705), "Ramsgate": (6380, 1650), "Broadstairs": (6390, 1678), "Westgate-on-Sea": (6325, 1700),
            "Birchington": (6305, 1690), "Canterbury": (6150, 1578), "Whitstable": (6110, 1665), "Herne Bay": (6175, 1680),
            "Faversham": (6015, 1615), "Dover": (6320, 1415), "Deal": (6375, 1525), "Sandwich": (6330, 1580),
            "Ashford": (6010, 1425), "Sittingbourne": (5905, 1635)}


def _os_town(e, n, within=60):
    best = min(OS_TOWNS.items(), key=lambda kv: (kv[1][0] - e) ** 2 + (kv[1][1] - n) ** 2)
    d = ((best[1][0] - e) ** 2 + (best[1][1] - n) ** 2) ** 0.5
    return best[0] if d <= within else None


def peoplebank(emp, places, today, cache, log=print):
    """Peoplebank vacancy list (Shepherd Neame pubs and hotels). Each row has the venue's OS grid position."""
    s, base = _session(), "https://www.peoplebank.com"
    t = s.get(base + emp["listing"], timeout=40).text
    jobs = []
    rows = re.findall(r'<div class="result"([^>]*)>([\s\S]*?)</div>\s*</div>', t)
    for attrs, body in rows:
        e = re.search(r'easting="(\d+)"', attrs)
        n = re.search(r'northing="(\d+)"', attrs)
        venue = (re.search(r'data-location="([^"]*)"', attrs) or [None, ""])[1]
        town = _os_town(int(e.group(1)), int(n.group(1))) if e and n else None
        if not town:
            continue
        title = _text((re.search(r'<h2[^>]*>([\s\S]*?)</h2>', body) or [None, ""])[1])
        closing = _anydate((re.search(r"Closing Date\s*([\d/]+)", body) or [None, ""])[1])
        href = (re.search(r'href="(/pbank/owa/pbk24w12\.main\?p=[^"]+)"', body) or [None, ""])[1]
        if not (title and closing and href):
            continue
        jobs.append(_job(emp, href.split("p=")[-1][:24], title, f"{html.unescape(venue)}, {town}", base + href, today,
                         closing=closing, description=(re.search(r'data-department="([^"]*)"', attrs) or [None, ""])[1]))
    log(f"{emp['name']}: {len(rows)} adverts listed, {len(jobs)} local jobs")
    return jobs


SPECIAL_MODES["peoplebank"] = peoplebank
