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
def employer_sitemap(emp, places, today, log=print):
    """
    Reads an employer's own careers site through its public sitemap + the structured
    JobPosting data on each advert (the data Google Jobs uses).
    Only adverts whose web address names one of our towns are opened, at the site's crawl-delay.
    A job is treated as open because it is listed on the employer's site today; if the advert has
    no closing date it is shown as "listed - apply soon" and re-checked every morning.
    """
    import json as _json
    s = requests.Session()
    s.headers.update(UA)
    base = emp["base"].rstrip("/")
    delay = float(emp.get("crawl_delay", 10))
    r = s.get(base + emp.get("sitemap", "/sitemap.xml"), timeout=30)
    r.raise_for_status()
    urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)
    urls = [u for u in urls if emp.get("job_path", "/jobs/") in u]
    towns = [p.lower().replace(" ", "-").replace(".", "") for p in places if not re.fullmatch(r"CT\d+", p)]
    local = [u for u in urls if re.search(r"(?:^|[-/])(?:" + "|".join(map(re.escape, towns)) + r")(?:[-./]|$)", u.lower())]
    log(f"{emp['name']}: {len(urls)} adverts on their site, {len(local)} name a local town")
    jobs = []
    for u in local:
        time.sleep(delay)
        try:
            p = s.get(u, timeout=30)
            if p.status_code != 200:
                continue
        except requests.RequestException:
            continue
        post = None
        for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>([\s\S]*?)</script>', p.text):
            try:
                data = _json.loads(block)
            except ValueError:
                continue
            for d in (data if isinstance(data, list) else data.get("@graph", [data])):
                if isinstance(d, dict) and d.get("@type") == "JobPosting":
                    post = d
        if not post:
            continue
        loc_obj = post.get("jobLocation") or {}
        if isinstance(loc_obj, list):
            loc_obj = loc_obj[0] if loc_obj else {}
        addr = loc_obj.get("address") or {}
        loc = f"{addr.get('addressLocality') or ''}, {addr.get('postalCode') or ''}"
        if not _thanet(loc + " " + u, places):
            continue
        sal = ((post.get("baseSalary") or {}).get("value") or {})
        pay = ""
        if isinstance(sal, dict) and (sal.get("value") or sal.get("minValue")):
            v = sal.get("value") or sal.get("minValue")
            unit = str(sal.get("unitText", "")).upper()
            pay = f"£{v} " + ("an hour" if unit == "HOUR" else "a year" if unit == "YEAR" else "")
        closing = _date(post.get("validThrough"))
        et = post.get("employmentType") or ""
        et = et[0] if isinstance(et, list) and et else et
        job = {
            "id": f"emp:{emp['name'].lower()}:" + str((post.get("identifier") or {}).get("value") or u.rsplit("/", 1)[-1]),
            "title": _text(post.get("title")),
            "employer": emp["name"],
            "pay": pay,
            "hours": {"FULL_TIME": "Full-time", "PART_TIME": "Part-time"}.get(str(et).upper(), ""),
            "location": loc, "job_type": "",
            "posted": str(_date(post.get("datePosted")) or ""),
            "description": _text(post.get("description"))[:12000],
            "closed_notice": False, "url": u, "source": emp["name"],
        }
        if closing:
            job["closing"] = str(closing)
        else:   # listed today, no closing date published: show for a week, re-checked daily
            job["closing"] = str(today + dt.timedelta(days=int(emp.get("show_days_without_closing", 8))))
            job["closing_estimated"] = True
            job["listed_only"] = True
        jobs.append(job)
    log(f"{emp['name']}: {len(jobs)} local jobs read")
    return jobs
