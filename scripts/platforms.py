"""
Readers for the off-the-shelf job systems many employers use. Each one reads the system's public
job feed (the same one the employer's own careers page uses), so adding a company is one line:
    {"name": "Example Ltd", "mode": "lever", "slug": "example"}
All of them return the same job dicts as sources._job, and keep only jobs in our area.
"""
import datetime as dt
import html
import re
import xml.etree.ElementTree as ET

import sources
from sources import _job, _session, _thanet, _text, _date, _pay_in_text, _hours

TIMEOUT = 45


def _ms(v):
    try:
        return str(dt.datetime.utcfromtimestamp(int(v) / 1000).date())
    except (TypeError, ValueError, OverflowError):
        return str(v or "")[:10]


def _keep(emp, places, today, out, ident, title, loc, url, desc="", closing=None, posted="", hours=""):
    if not title or not _thanet(f"{loc}", places):
        return
    out.append(_job(emp, ident, title, loc, url, today, pay=_pay_in_text(desc), hours=hours or _hours(f"{title} {desc[:300]}"),
                    closing=closing, posted=posted, description=desc))


def lever(emp, places, today, cache, log=print):
    s = _session()
    host = "https://api.eu.lever.co" if emp.get("eu") else "https://api.lever.co"
    d = s.get(f"{host}/v0/postings/{emp['slug']}", params={"mode": "json"}, timeout=TIMEOUT).json()
    out = []
    for x in d if isinstance(d, list) else []:
        cat = x.get("categories") or {}
        locs = " / ".join([cat.get("location") or ""] + list(cat.get("allLocations") or []))
        _keep(emp, places, today, out, x.get("id"), x.get("text"), locs, x.get("hostedUrl"),
              desc=x.get("descriptionPlain") or _text(x.get("description")), posted=_ms(x.get("createdAt")),
              hours=_hours(cat.get("commitment") or ""))
    log(f"{emp['name']}: {len(d) if isinstance(d, list) else 0} adverts (Lever), {len(out)} local jobs")
    return out


def smartrecruiters(emp, places, today, cache, log=print):
    s, out, offset, total = _session(), [], 0, None
    while total is None or offset < min(total, 1000):
        d = s.get(f"https://api.smartrecruiters.com/v1/companies/{emp['slug']}/postings",
                  params={"limit": 100, "offset": offset, "country": "gb"}, timeout=TIMEOUT).json()
        total = d.get("totalFound", 0)
        rows = d.get("content") or []
        for x in rows:
            l = x.get("location") or {}
            loc = ", ".join(v for v in [l.get("city"), l.get("region"), l.get("fullLocation")] if v)
            _keep(emp, places, today, out, x.get("id"), x.get("name"), loc,
                  f"https://jobs.smartrecruiters.com/{emp['slug']}/{x.get('id')}",
                  posted=str(x.get("releasedDate") or "")[:10], hours=_hours((x.get("typeOfEmployment") or {}).get("label") or ""))
        if not rows:
            break
        offset += 100
    log(f"{emp['name']}: {total or 0} adverts (SmartRecruiters), {len(out)} local jobs")
    return out


def workable(emp, places, today, cache, log=print):
    d = _session().get(f"https://apply.workable.com/api/v1/widget/accounts/{emp['slug']}", timeout=TIMEOUT).json()
    out = []
    for x in d.get("jobs") or []:
        locs = [x.get("city") or "", x.get("state") or ""] + [l.get("city") or "" for l in x.get("locations") or []]
        _keep(emp, places, today, out, x.get("shortcode"), x.get("title"), ", ".join(v for v in locs if v),
              x.get("url") or x.get("application_url"), posted=str(x.get("published_on") or "")[:10],
              hours=_hours(x.get("employment_type") or ""))
    log(f"{emp['name']}: {len(d.get('jobs') or [])} adverts (Workable), {len(out)} local jobs")
    return out


def recruitee(emp, places, today, cache, log=print):
    d = _session().get(f"https://{emp['slug']}.recruitee.com/api/offers/", timeout=TIMEOUT).json()
    out = []
    for x in d.get("offers") or []:
        loc = ", ".join(v for v in [x.get("city"), x.get("location"), x.get("postal_code")] if v)
        _keep(emp, places, today, out, x.get("id"), x.get("title"), loc, x.get("careers_url"),
              desc=_text(x.get("description")), closing=_date(x.get("close_at")), posted=str(x.get("published_at") or "")[:10],
              hours=_hours(x.get("employment_type_code") or ""))
    log(f"{emp['name']}: {len(d.get('offers') or [])} adverts (Recruitee), {len(out)} local jobs")
    return out


def pinpoint(emp, places, today, cache, log=print):
    d = _session().get(f"https://{emp['slug']}.pinpointhq.com/postings.json", timeout=TIMEOUT).json()
    out = []
    for x in d.get("data") or []:
        l = x.get("location") or {}
        loc = ", ".join(v for v in [l.get("city"), l.get("name"), l.get("province"), l.get("postal_code")] if isinstance(v, str) and v)
        _keep(emp, places, today, out, x.get("id"), x.get("title"), loc, x.get("url"),
              desc=_text(x.get("description")), closing=_date(x.get("deadline_at")), hours=_hours(x.get("employment_type_text") or ""))
    log(f"{emp['name']}: {len(d.get('data') or [])} adverts (Pinpoint), {len(out)} local jobs")
    return out


def ashby(emp, places, today, cache, log=print):
    d = _session().get(f"https://api.ashbyhq.com/posting-api/job-board/{emp['slug']}", timeout=TIMEOUT).json()
    out = []
    for x in d.get("jobs") or []:
        addr = ((x.get("address") or {}).get("postalAddress") or {})
        loc = ", ".join(v for v in [x.get("location"), addr.get("addressLocality"), addr.get("postalCode")] if v)
        _keep(emp, places, today, out, x.get("id") or x.get("jobUrl"), x.get("title"), loc, x.get("jobUrl"),
              desc=x.get("descriptionPlain") or "", posted=str(x.get("publishedAt") or "")[:10], hours=_hours(x.get("employmentType") or ""))
    log(f"{emp['name']}: {len(d.get('jobs') or [])} adverts (Ashby), {len(out)} local jobs")
    return out


def personio(emp, places, today, cache, log=print):
    dom = emp.get("domain", "de")
    t = _session().get(f"https://{emp['slug']}.jobs.personio.{dom}/xml", timeout=TIMEOUT).text
    out, n = [], 0
    try:
        root = ET.fromstring(t)
    except ET.ParseError:
        root = None
    for p in (root.findall(".//position") if root is not None else []):
        n += 1
        g = lambda k: (p.findtext(k) or "").strip()
        desc = " ".join(_text(html.unescape(v.findtext("value") or "")) for v in p.findall(".//jobDescription"))
        _keep(emp, places, today, out, g("id"), g("name"), g("office"),
              f"https://{emp['slug']}.jobs.personio.{dom}/job/{g('id')}", desc=desc, posted=g("createdAt")[:10],
              hours=_hours(g("schedule")))
    log(f"{emp['name']}: {n} adverts (Personio), {len(out)} local jobs")
    return out


def teamtailor(emp, places, today, cache, log=print):
    base = emp.get("base") or f"https://{emp['slug']}.teamtailor.com"
    t = _session().get(base.rstrip("/") + "/jobs.rss", timeout=TIMEOUT).text
    out, n = [], 0
    for item in re.findall(r"<item>([\s\S]*?)</item>", t):
        n += 1
        g = lambda tag: html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", item) or [None, ""])[1])).strip()
        locs = " ".join(re.findall(r"<tt:(?:city|location|name)[^>]*>([^<]*)<", item))
        desc = _text(g("description"))
        _keep(emp, places, today, out, g("guid") or g("link"), g("title"), f"{locs} {desc[:400]}", g("link"), desc=desc)
    log(f"{emp['name']}: {n} adverts (Teamtailor), {len(out)} local jobs")
    return out


MODES = {"lever": lever, "smartrecruiters": smartrecruiters, "workable": workable, "recruitee": recruitee,
         "pinpoint": pinpoint, "ashby": ashby, "personio": personio, "teamtailor": teamtailor}
sources.SPECIAL_MODES.update(MODES)

# How to spot each system on a careers page: (mode, pattern capturing the company's slug)
DETECT = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9._-]+)"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("recruitee", r"//([A-Za-z0-9-]+)\.recruitee\.com"),
    ("pinpoint", r"//([A-Za-z0-9-]+)\.pinpointhq\.com"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9._-]+)"),
    ("personio", r"//([A-Za-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
    ("teamtailor", r"//([A-Za-z0-9-]+)\.teamtailor\.com"),
]
# Systems we know we cannot read (they block automated reading or need a login)
UNSUPPORTED = [("workday", r"myworkdayjobs\.com|workday\.com/.*/job"), ("successfactors", r"successfactors\.(?:com|eu)|jobs\.sap\.com"),
               ("taleo", r"taleo\.net"), ("icims", r"icims\.com"), ("oracle", r"oraclecloud\.com/hcmUI"),
               ("avature", r"avature\.net"), ("jobvite", r"jobs\.jobvite\.com")]
NOISE_SLUGS = {"embed", "js", "css", "static", "api", "www", "jobs", "careers", "assets", "cdn"}
