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
