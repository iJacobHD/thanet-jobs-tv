"""
Reed.co.uk official Jobseeker API -> job dicts in the same shape the filters use.
Docs: https://www.reed.co.uk/developers/jobseeker
Auth: API key as the Basic-auth username, empty password.
"""
import datetime as dt
import html
import re
import time

import requests

BASE = "https://www.reed.co.uk/api/1.0"


def _g(d, *names, default=""):
    """Read a field whatever its exact capitalisation (the docs list labels, not keys)."""
    low = {k.lower(): v for k, v in d.items()}
    for n in names:
        v = low.get(n.lower())
        if v not in (None, ""):
            return v
    return default


def _date(s):
    s0 = str(s or "").strip().split("T")[0].split(" ")[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s0, fmt).date()
        except ValueError:
            pass
    return None


def _text(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(h or "")))).strip()


def _pay(d):
    lo, hi = _g(d, "minimumSalary"), _g(d, "maximumSalary")
    unit = str(_g(d, "salaryType", "salary_type")).lower()
    if not lo and not hi:
        return ""
    per = "an hour" if "hour" in unit else "a day" if "day" in unit else "a week" if "week" in unit else "a month" if "month" in unit else "a year"
    if not unit:
        per = "an hour" if float(lo or hi) < 100 else "a year"
    lo, hi = lo or hi, hi or lo
    return f"£{lo} to £{hi} {per}"


def fetch(api_key, location="Margate", miles=10, delay=0.3, log=print, places=None):
    """places: only open the full advert for results whose location matches one of these."""
    s = requests.Session()
    s.auth = (api_key, "")
    s.headers["User-Agent"] = "ThanetJobsTV/1.0"

    def get(url, params=None):
        for attempt in range(3):
            r = s.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()

    results, skip = [], 0
    while True:
        data = get(f"{BASE}/search", {"locationName": location, "distanceFromLocation": miles,
                                      "resultsToTake": 100, "resultsToSkip": skip})
        page = _g(data, "results", default=[]) or []
        results += page
        total = int(_g(data, "totalResults", default=0) or 0)
        log(f"Reed search: {len(results)} of {total}")
        skip += 100
        if not page or skip >= total or skip >= 2000:
            break
        time.sleep(delay)

    if places:
        pat = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in places) + r")\b", re.I)
        results = [r for r in results if pat.search(str(_g(r, "locationName")))]
        log(f"Reed: {len(results)} results are in Thanet")
    jobs = []
    for r in results:
        jid = str(_g(r, "jobId", "id"))
        loc = str(_g(r, "locationName"))
        detail = {}
        try:
            time.sleep(delay)
            detail = get(f"{BASE}/jobs/{jid}") or {}
        except Exception as e:  # keep going with the search data
            log(f"  details for {jid} failed: {e}")
        d = {**r, **detail}
        closing = _date(_g(d, "expirationDate", "expiryDate", "closingDate"))
        jobs.append({
            "id": jid,
            "title": _text(_g(d, "jobTitle", "title")),
            "employer": _text(_g(d, "employerName")),
            "pay": _pay(d),
            "hours": str(_g(d, "jobType", "contractTime")).replace("_", " ").title(),
            "location": loc or _text(_g(d, "locationName")),
            "job_type": str(_g(d, "contractType")).title(),
            "posted": str(_date(_g(d, "datePosted", "date")) or ""),
            "closing": str(closing or ""),
            "description": _text(_g(d, "jobDescription", "description"))[:12000],
            "closed_notice": False,
            "url": _g(d, "jobUrl", "url", default=f"https://www.reed.co.uk/jobs/{jid}"),
        })
    return jobs
