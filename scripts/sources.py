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
                     r"no longer accepting applications|this job (?:is no longer available|has expired)|position has been filled)", re.I)


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
    title = prop("title") or _text((re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html_text) or [None, ""])[1])
    loc = " ".join(x for x in [prop("addressLocality"), prop("addressRegion"), prop("postalCode")] if x)
    if not (title and loc):
        return None
    return {"title": title, "description": prop("description")[:12000] or _text(html_text)[:12000],
            "jobLocation": {"address": {"addressLocality": loc}},
            "validThrough": prop("validThrough"), "datePosted": prop("datePosted"),
            "employmentType": prop("employmentType")}


def _fields(html_text):
    """Labelled fields on the page ('Location Newry  Salary: ...  Closing Date: 10 Dec 2026  Vacancy Type: Full Time') - Eploy sites (B&M, Travelodge)."""
    body = _text(re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html_text))
    t = re.search(r"<title>([\s\S]*?)</title>", html_text)
    title = _text(t.group(1)).split(" - ")[0].split(" | ")[0] if t else ""
    loc = re.search(r"\bLocation:?\s*([A-Z][^:]{1,60}?)\s+(?:Location is a required|Salary|Pay\b|Position|Vacancy Type|Date Posted|Closing)", body)
    if not (title and loc):
        return None
    pay = re.search(r"(?:Salary|Pay):?\s*(£[^A-Z]{1,60}?)(?=\s+[A-Z])", body)
    close = re.search(r"Closing Date:?\s*([^A-Z]{0,3}\d{1,2}\s+\w+\s+\d{4})", body)
    posted = re.search(r"Date Posted:?\s*(\d{1,2}\s+\w+\s+\d{4})", body)
    vt = re.search(r"Vacancy Type:?\s*(Full|Part)[ -]?Time", body, re.I)
    return {"title": title, "description": body[:12000],
            "jobLocation": {"address": {"addressLocality": loc.group(1)}},
            "baseSalary": {"value": {"value": pay.group(1).strip() if pay else ""}},
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
        if not _thanet(text, places):
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
    while page < pages and page < 20:
        r = s.post(base + "/wp-json/posts/search", timeout=40,
                   data={"paginate[page]": page, "paginate[per_page]": 100, "status[]": "publish"})
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


SPECIAL_MODES = {"listing": listing_pages, "costa": costa, "phenom": phenom, "xml_feed": xml_feed,
                 "greenhouse": greenhouse, "aspnet_grid": aspnet_grid}
