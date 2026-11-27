#!/usr/bin/env python3
"""
Thanet Jobs TV - data updater.

Pulls live vacancies from the DWP job site (Work Hub, jobs.service.gov.uk),
keeps only jobs that are:
  * in Thanet,
  * still open (closing date in the future),
  * entry level (no experience / qualifications demanded),
  * NOT self-employed,
then writes docs/jobs.json (with a QR code for each job) for the TV display.

Run:  python scripts/update_jobs.py
Test without internet:  python scripts/update_jobs.py --from-dump dump.json
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from qr import make_qr, to_svg_path  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://www.jobs.service.gov.uk"
UA = "ThanetJobsTV/1.0 (community job board display; polite, cached, a few requests per run)"

# --------------------------------------------------------------------------- rules
SELF_EMPLOYED = [
    r"self[\s-]?employ", r"\bfreelance\b", r"\bfranchise\b", r"commission[\s-]only",
    r"be your own boss", r"pay per (audit|delivery|drop|visit|job)", r"\bper audit\b",
    r"\bsole trader\b", r"\bumbrella company\b", r"\bgig (?:work|economy)\b",
    r"unique taxpayer reference", r"\bsubcontractor\b",
]

# Phrases that SAY experience isn't needed - removed from the text before the
# experience rules run, so "No experience is required" never counts as "experience is required".
NOT_NEEDED = [
    r"no (?:previous |prior |formal )?(?:experience|qualifications?)\s*(?:is |are )?(?:needed|necessary|required|neccessary|essential)?",
    r"(?:experience|qualifications?)[^.]{0,160}(?:not essential|not required|not necessary|not a necessity|advantageous|an advantage|desirable|a bonus|a plus|beneficial|preferred but|welcome but)",
    r"(?:licen[cs]e|certificate|card|qualification)s?[^.]{0,40}(?:is |are |would be )?(?:preferred|desirable|advantageous|an advantage|a bonus|a plus|beneficial|not essential|not required)",
    r"routes? towards?[^.]{0,160}", r"qualified teacher (?:training|status)[^.]{0,40}if desired",
    r"not necessarily your experience", r"key skills\s*/?\s*experience required",
    r"whether you have years of experience", r"experience and skills? (?:we.re|we are) looking for",
    r"what skills and experience we.re looking for", r"up to degree level", r"degree level",
    r"(?:towards|toward|to gain|achieve|funded|fully funded|including)[^.]{0,40}(?:qualification|level\s*\d|nvq|qts|diploma|certificate)",
]

EXPERIENCE = [
    r"\d+\s*\+?\s*(?:-|to)?\s*\d*\s*(?:years?|yrs?)['’]?\s*(?:of\s+)?(?:relevant\s+|previous\s+|proven\s+|working\s+)?experience",
    r"experience\s+(?:is\s+)?(?:essential|required|necessary|a must)",
    r"experience and skills required", r"(?:essential|required) experience",
    r"(?:must|should|will)\s+(?:already\s+)?have\s+(?:previous\s+|prior\s+|relevant\s+|proven\s+|the\s+)?experience",
    r"(?:proven|previous|prior|demonstrable|significant|extensive|relevant)\s+experience\s+(?:in|of|as|within|working|operating|using|with)",
    r"have\s+experience\s+in\s+a\s+similar\s+role",
    r"(?:we are|we're|are you|looking for|seeking|recruit)\s+(?:an?\s+)?(?:highly\s+|suitably\s+)?experienced\b",
    r"\bexperienced\s+(?:and\s+\w+\s+)?(?:carer|cleaner|chef|cook|driver|nurse|teacher|support worker|house cleaner|professional|practitioner|teaching assistant)s?",
    r"experienced in [^.()]{0,40}\(?essential",
    r"some experience as an?", r"band\s*[3-9]\b", r"experience[^.]{0,80}is a must",
]
QUALIFICATION = [
    r"(?:must|should|will)\s+(?:have|hold)\s+QTS", r"QTS\s+(?:is\s+)?(?:essential|required)", r"\bwith QTS\b",
    r"\bNMC\b", r"\bHCPC\b", r"\bGMC\b", r"\bregistered (?:nurse|manager|social worker|midwife)",
    r"degree\s+(?:is\s+)?(?:essential|required)", r"(?:must|should)\s+(?:have|hold)\s+a\s+(?:relevant\s+)?degree",
    r"degree[- ]educated", r"educated to degree",
    r"(?:must|should)\s+(?:have|hold)\s+(?:an?\s+)?(?:level|nvq)\s*[3-7]",
    r"level\s*[3-7]\s+(?:\w+\s+){0,4}(?:qualification|diploma|certificate|award)[^.]{0,30}(?:essential|required)",
    r"\b(?:hgv|lgv|pcv|cpc|class\s*[12] licen[cs]e|c1 licen[cs]e|ppt licen[cs]e|ppt licen[cs]e)\b",
    r"\bSIA (?:licen[cs]e|badge)\b", r"\bchartered\b",
    r"\bqualified\s+(?:teacher|chef|electrician|plumber|accountant|nurse|engineer|mechanic|technician)",
    r"\bfully qualified\b",
]
# Cards a beginner can get in days (CSCS test, forklift course) - keep the job, show a badge instead of hiding it
CARD_NEEDED = [
    ("CSCS card", r"\bCSCS\b"),
    ("Forklift licence", r"\b(?:forklift|fork lift|flt|counterbalance|reach truck|rtitb|mhe)\b[^.]{0,40}\b(?:licen[cs]e|ticket|certificat\w*|qualif\w*)\b(?![^.]{0,30}\b(?:provided|given|desirable|preferred|not essential|an advantage)\b)"),
    ("Forklift licence", r"\b(?:licen[cs]e|ticket|certificat\w*)\b[^.]{0,20}\b(?:forklift|flt|counterbalance|reach truck)\b"),
]


def card_needed(text):
    for label, pat in CARD_NEEDED:
        if re.search(pat, text, re.I):
            return label
    return ""


SENIOR_TITLES = [
    r"\bmanager\b", r"\bsupervisor\b", r"\bteam leader\b", r"\bsenior\b", r"\blead\b", r"\bhead of\b",
    r"\bdeputy\b", r"\bdirector\b", r"\bconsultant\b", r"\bteacher\b", r"\blecturer\b", r"\bnurse\b",
    r"\bmidwife\b", r"\bengineer\b", r"\bsurgeon\b", r"\bparamedic\b", r"\b(?:anp|acp)\b", r"\bphysio",
    r"\b(?:gp|doctor|psychiatrist|dermatologist|physician|pharmacist|gastroenterologist)\b",
    r"\bsolicitor\b", r"\btherapist\b", r"\banalyst\b", r"\baccountant\b", r"\bcontroller\b",
    r"\bspecialist\b", r"\bpractitioner\b", r"\bco-?ordinator\b", r"\bofficer\b",
    r"\bplanner\b", r"\bbuyer\b", r"\bdesigner\b", r"\bdeveloper\b", r"\bfellow\b", r"\blocum\b",
    r"\bchef\b", r"\bveterinary\b", r"\bvet\b", r"\btechnician\b", r"\belectrician\b", r"\bplumber\b",
    r"\bscientist\b", r"\bsocial worker\b", r"\bprofessor\b", r"\b(?:hgv|lgv|class [12]) driver\b",
    r"\badvis[oe]r\b", r"\bnavigator\b", r"\binspector\b", r"\bsurveyor\b", r"\bminder\b",
    r"\bsite manager\b", r"\bestimator\b", r"\bfitter\b", r"\bwelder\b", r"\bmechanic\b",
    r"\bjoiner\b", r"\bcarpenter\b", r"\bbricklayer\b", r"\bplasterer\b", r"\bpainter and decorator\b",
    r"\bfield sales\b", r"\bsales executive\b", r"\bbusiness development\b",
    r"\bhlta\b", r"\bhigher level teaching\b", r"\bsetter\b", r"\bsecretary\b", r"\bgraduate\b",
    r"\btutor\b", r"\bphysiologist\b", r"\bechocardiograph", r"\bhead\b", r"\bqualified\b",
    r"\bradiograph", r"\bpharmac", r"\bparalegal\b", r"\bsurveyor\b", r"\barchitect\b",
    r"\bcnc\b", r"\bmachinist\b", r"\bpsycholog", r"\bcounsell?or\b", r"\bsenco\b", r"\bpartner\b", r"\bassociate (?:dentist|director)\b",
]
NO_EXPERIENCE = [
    r"no (?:previous |prior )?experience\s*(?:is )?(?:needed|necessary|required|neccessary)?",
    r"full(?:,| and)? (?:paid )?training (?:is )?(?:given|provided)",
    r"training (?:is )?(?:provided|given)", r"experience (?:is )?not essential",
    r"don.t need any experience", r"we.ll train you", r"willing to learn",
]
LICENCE = [
    r"(?:driving licen[cs]e|driver.s licen[cs]e|own (?:car|vehicle)|access to (?:a |your own |own )?(?:car|vehicle)|car drivers?|drivers?)\b[^.]{0,80}(?:essential|required|must|needed|necessary|\byes\b)",
    r"(?:must|need to|required to|will need to)\s+(?:have|hold|be)\s+[^.]{0,40}(?:licen[cs]e|car|vehicle|driver)\b",
    r"requires?d?\s+(?:a\s+)?(?:full\s+|valid\s+|clean\s+)?(?:uk\s+)?driving licen[cs]e",
    r"essential[^.]{0,40}(?:driving licen[cs]e|own car|own vehicle)", r"\bcar required\b", r"must (?:be able to )?drive",
]
NOT_LICENCE = [
    r"(?:licen[cs]es?|cars?|vehicles?|drivers?|driving)\b[^.,;]{0,25}(?:desirable|preferred|not essential|an advantage|isn.t essential|is not essential|would be useful)",
    r"driving isn.t essential", r"(?:desirable|preferred)[^.,;]{0,30}(?:licen[cs]e|driver)",
    r"own transport when required",
]
LICENCE_WORDS = r"driving licen[cs]e|driver.s licen[cs]e|own car|own vehicle|access to (?:a |your own )?(?:car|vehicle)|car driver"


def needs_licence(job):
    text = re.sub("|".join(NOT_LICENCE), " ", f"{job['title']} . {job['description']}", flags=re.I)
    if _any(LICENCE, text):
        return True
    m = re.search(r"Essential requirements:(.*?)(?: \. [A-Z][\w ]{2,40}:|$)", text)
    return bool(m and re.search(LICENCE_WORDS, m.group(1), re.I))


def _any(patterns, text):
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(0)
    return None


# --------------------------------------------------------------------------- parsing
def parse_search(html):
    soup = BeautifulSoup(html, "html.parser")
    ids = []
    for el in soup.select('[data-testid^="searchResultCard-"]'):
        jid = el["data-testid"].split("-", 1)[1]
        if re.fullmatch(r"[0-9a-f]{24}", jid) and jid not in ids:
            ids.append(jid)
    if not ids:  # fallback: any link to a job advert
        for a in soup.find_all("a", href=True):
            m = re.fullmatch(r"/jobs/([0-9a-f]{24})", a["href"])
            if m and m.group(1) not in ids:
                ids.append(m.group(1))
    total = None
    m = re.search(r"of\s*<strong>\s*([\d,]+)\s*</strong>", html)
    if m:
        total = int(m.group(1).replace(",", ""))
    return ids, total


def _tid(soup, name):
    el = soup.select_one(f'[data-testid="{name}"]')
    if not el:
        return ""
    for b in el.find_all("button"):
        b.decompose()
    txt = re.sub(r"\s+", " ", el.get_text(" "))
    txt = re.sub(r"\(\s*(?:View on map)?\s*\)", "", txt)
    return txt.strip()


def parse_date(s):
    s = (s or "").strip().replace("Sept", "Sep")
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def parse_detail(html, jid):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one('[data-testid="pageHeading"]') or soup.find("h1")
    # Summary + "Essential requirements" + any other sections, stopping at "Related jobs"
    sections = []
    for h2 in soup.find_all("h2"):
        name = h2.get_text(" ", strip=True)
        if re.search(r"related jobs", name, re.I):
            break
        sib = h2.find_next_sibling()
        if sib is not None:
            sections.append(f"{name}: " + sib.get_text(" "))
    if not sections:
        el = soup.select_one(".rawHtmlContainer")
        sections = [el.get_text(" ")] if el else []
    desc = re.sub(r"\s+", " ", " . ".join(sections))
    page_text = re.sub(r"\s+", " ", soup.get_text(" "))
    return {
        "id": jid,
        "title": h1.get_text(" ", strip=True) if h1 else "",
        "employer": _tid(soup, "companyName"),
        "pay": _tid(soup, "salary"),
        "hours": _tid(soup, "jobPattern"),
        "location": _tid(soup, "location"),
        "job_type": _tid(soup, "jobType"),
        "posted": str(parse_date(_tid(soup, "postingDate")) or ""),
        "closing": str(parse_date(_tid(soup, "closingDate")) or ""),
        "description": desc[:12000],
        "closed_notice": bool(re.search(r"no longer accepting|this job has (?:closed|expired)|vacancy (?:has )?closed", page_text, re.I)),
        "url": f"{BASE}/jobs/{jid}",
    }


# --------------------------------------------------------------------------- classify
def commute_minutes(location, cfg):
    """Door-to-door public transport minutes for a job location, from the commute table."""
    com = cfg.get("commute")
    if not com:
        return None
    for name in sorted(com["towns"], key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"\b", location, re.I):
            return com["towns"][name]
    m = re.search(r"\b([A-Z]{1,2}\d{1,2})\s*\d[A-Z]{2}\b|\b([A-Z]{1,2}\d{1,2})\b", location.upper())
    if m:
        return com["postcodes"].get(m.group(1) or m.group(2))
    return None


def shown_minutes(town, cfg):
    """Typical bus/train time from Margate shown on the card - looked up by the card's town so it is always consistent."""
    table = (cfg.get("commute") or {}).get("shown_minutes", {})
    for name in sorted(table, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"\b", town, re.I):
            return table[name]
    return None


def nice_town(t, cfg):
    return (cfg.get("commute") or {}).get("postcode_names", {}).get(t, t)


def town_of(location, places):
    places = sorted(places, key=lambda p: (("Westwood" not in p), -len(p)))   # Westwood Cross first, then longest names
    for p in places:
        if re.search(r"\b" + re.escape(p) + r"\b", location, re.I):
            if p.upper().startswith("CT"):
                continue
            return "St Peter's" if "Peter" in p else p
    return "Thanet"


def annual_min(pay):
    nums = [float(n.replace(",", "")) for n in re.findall(r"£\s*([\d,]+(?:\.\d+)?)", pay)]
    if not nums:
        return None
    lo = min(nums)
    if re.search(r"a year|per annum|annum|p\.?a\.?", pay, re.I) or lo > 1000:
        return lo
    return None


APPRENTICE = re.compile(r"\bapprentic(?:e|eship|eships)\b", re.I)


def is_apprenticeship(job):
    return (job.get("source") == "Find an apprenticeship" or str(job.get("job_type", "")).lower() == "apprenticeship"
            or bool(APPRENTICE.search(job.get("title", ""))))


def classify_apprenticeship(job, cfg, today):
    """Apprenticeships are entry-level by design (paid training), so only the area, closing date,
    blocked-employer and self-employed checks apply - not the experience/qualification/pay rules."""
    for bad in cfg.get("exclude_places", []):
        if re.search(r"\b" + re.escape(bad) + r"\b", f"{job['location']} {job['title']}", re.I):
            return False, f"outside the commute area ({bad})", {}
    if not any(re.search(r"\b" + re.escape(p) + r"\b", job["location"], re.I) for p in cfg["allowed_places"]):
        return False, "outside the commute area", {}
    mins = commute_minutes(job["location"], cfg)
    if cfg.get("commute") and (mins is None or mins > cfg["commute"].get("max_minutes", 90)):
        return False, "over the commute limit", {}
    closing = parse_date_iso(job["closing"])
    if job.get("closed_notice") or not closing or (closing - today).days < cfg.get("hide_when_days_left_below", 1):
        return False, "closed / no closing date", {}
    emp = job["employer"].lower()
    for b in cfg.get("blocked_employers", []):
        if b.lower() in emp:
            return False, "blocked employer", {}
    if _any(SELF_EMPLOYED, f"{job['job_type']} . {job['title']} . {job['description']}"):
        return False, "self-employed", {}
    return True, "ok", {"licence": needs_licence(job), "no_experience": True, "travel_minutes": mins}


SITE = "https://eastkentjobs.github.io/"


def go_id(jid):
    """Short, stable id for the job's phone page (keeps the QR code small and quick to scan)."""
    import hashlib
    n = int(hashlib.sha1(jid.encode()).hexdigest()[:10], 16)
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + out
    return out


def qr_for(jid):
    link = SITE + "go.html?j=" + go_id(jid)
    m = make_qr(link, "M")
    return {"path": to_svg_path(m, border=0), "size": len(m)}, link


def board_entry(jid, job, cfg, flags):
    qr, go_link = qr_for(jid)
    return {
        "id": jid,
        "go": go_id(jid),
        "place": job.get("location", ""),
        "title": clean_title(job["title"]),
        "employer": tidy_employer(job["employer"]),
        "town": nice_town(town_of(job["location"], cfg["allowed_places"]), cfg),
        "pay": tidy_pay(job["pay"], job["description"]),
        "hours": job["hours"],
        "contract": job["job_type"],
        "closing": job["closing"],
        "licence": flags["licence"],
        "card": flags.get("card", ""),
        "travel_minutes": shown_minutes(nice_town(town_of(job["location"], cfg["allowed_places"]), cfg), cfg) or flags.get("travel_minutes"),
        "no_experience": flags["no_experience"],
        "url": job["url"],
        "source": job.get("source", "DWP Find a Job"),
        "posted": job.get("posted", ""),
        "closing_estimated": bool(job.get("closing_estimated")),
        "listed_only": bool(job.get("listed_only")),
        "qr": qr,
    }


# Reasons that only mean "not a first job" - the advert is local, open and genuine, so it belongs
# on the careers side (Pathway) even though it never goes on the TV board.
LEVEL_REASONS = (("not entry level", "Senior / management"), ("asks for experience", "Needs experience"),
                 ("needs a qualification", "Needs a qualification"), ("pay range suggests", "Higher pay"),
                 ("salary too high", "Higher pay"), ("NHS Band 3+", "Needs experience"))


def career_level(reason):
    for start, label in LEVEL_REASONS:
        if reason.startswith(start):
            return label
    return ""


NO_DATE = "no closing date (cannot prove it is open)"


def undated_entry(jid, job, cfg, today):
    """A job with no closing date can't go on the TV (the video plays all week), but it was listed in this
    morning's feed, so it is open today: Pathway (rebuilt every morning) shows it as 'no closing date'."""
    trial = dict(job, closing=str(today + dt.timedelta(days=30)))
    ok, why, _ = classify(trial, cfg, today)
    lvl = "Entry level" if ok else career_level(why)
    if not lvl:
        return None
    e = career_entry(jid, job, cfg, lvl)
    e.update(closing="", nodate=True, entry=ok)
    return e


def career_entry(jid, job, cfg, level):
    return {
        "id": jid, "title": clean_title(job["title"]), "employer": tidy_employer(job["employer"]),
        "town": nice_town(town_of(job["location"], cfg["allowed_places"]), cfg),
        "pay": tidy_pay(job["pay"], job["description"]), "hours": job["hours"],
        "closing": job["closing"], "url": job["url"], "level": level, "source": job.get("source", ""),
    }


def still_open(job, today, cfg):
    d = parse_date_iso(job.get("closing"))
    return bool(d) and not job.get("closed_notice") and (d - today).days >= cfg.get("hide_when_days_left_below", 1)


def write_careers(careers, failed, used, cfg, today):
    """docs/careers.json - every local job that needs experience or qualifications. Shown on Pathway only."""
    path = os.path.join(ROOT, "docs", "careers.json")
    if failed:       # keep yesterday's for feeds that failed today
        try:
            prev = json.load(open(path, encoding="utf-8"))
            careers += [j for j in prev.get("jobs", []) if j.get("source") in failed and not j.get("nodate") and j.get("closing", "") > str(today)]
        except (OSError, ValueError):
            pass
    seen, out = set(), []
    for j in sorted(careers, key=lambda j: j["closing"] or "9999"):
        key = (j["title"].lower(), j["employer"].lower(), j["town"].lower())
        if key not in seen:
            seen.add(key); out.append(j)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "count": len(out), "jobs": out}, fh, ensure_ascii=False, indent=0)
    print(f"careers.json: {len(out)} experienced / qualified jobs")


def write_health(found_by, failed, cfg, today):
    """Spot broken readers: a source that has found nothing for 7+ days usually means its website changed."""
    path = os.path.join(ROOT, "data", "source_health.json")
    try:
        h = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        h = {}
    for name in set(found_by) | set(failed):
        e = h.setdefault(name, {"first_seen": str(today), "last_found": ""})
        e["last_count"] = found_by.get(name, 0)
        e["failed_today"] = name in failed
        if found_by.get(name, 0) > 0:
            e["last_found"] = str(today)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(h, fh, indent=1, sort_keys=True)
    stale = []
    for name, e in sorted(h.items()):
        since = e.get("last_found") or e.get("first_seen")
        if (today - dt.date.fromisoformat(since)).days >= 7 and name in (set(found_by) | set(failed)):
            stale.append({"name": name, "since": e.get("last_found") or "", "failing": e.get("failed_today", False)})
    with open(os.path.join(ROOT, "docs", "health.json"), "w", encoding="utf-8") as fh:
        json.dump({"checked": str(today), "stale": stale}, fh, ensure_ascii=False)
    if stale:
        print("!! Sources with no jobs for 7+ days: " + ", ".join(x["name"] for x in stale))


def write_go_index(today):
    """docs/go.json - what each QR code's phone page shows. Kept 30 days so a code on last week's
    USB video still works after the job drops off the board."""
    path = os.path.join(ROOT, "docs", "go.json")
    try:
        idx = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        idx = {}
    for name in ("jobs.json", "apprenticeships.json"):
        try:
            jobs = json.load(open(os.path.join(ROOT, "docs", name), encoding="utf-8"))["jobs"]
        except (OSError, ValueError, KeyError):
            continue
        for j in jobs:
            idx[j.get("go") or go_id(j["id"])] = {
                "t": j["title"], "e": j["employer"], "town": j["town"], "place": j.get("place") or j["town"],
                "pay": j["pay"], "hours": j.get("hours", ""), "closing": j["closing"],
                "est": bool(j.get("closing_estimated") or j.get("listed_only")), "url": j["url"],
                "app": name.startswith("app"), "seen": str(today)}
    cutoff = str(today - dt.timedelta(days=30))
    idx = {k: v for k, v in idx.items() if v["seen"] >= cutoff}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(idx, fh, ensure_ascii=False, separators=(",", ":"))


def write_apprenticeships(apps, failed, used, cfg, today):
    """docs/apprenticeships.json - the separate apprenticeship board and video."""
    path = os.path.join(ROOT, "docs", "apprenticeships.json")
    if failed:
        try:
            prev = json.load(open(path, encoding="utf-8"))
            apps += [j for j in prev.get("jobs", []) if j.get("source") in failed and j.get("closing", "") > str(today)]
        except (OSError, ValueError):
            pass
    seen, unique = set(), []
    for j in sorted(apps, key=lambda j: (j.get("source") != "Find an apprenticeship", j["closing"])):
        k = (re.sub(r"[^a-z0-9]", "", j["title"].lower()), j["town"].lower(), re.sub(r"[^a-z0-9]", "", j["employer"].lower())[:12])
        if k not in seen:
            seen.add(k)
            unique.append(j)
    unique.sort(key=lambda j: (j["closing"], j["title"]))
    srcs = sorted({j["source"] for j in unique})
    out = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": (", ".join(srcs) or "no apprenticeships found today") +
                     (". Find an apprenticeship data under the Open Government Licence v3.0" if "Find an apprenticeship" in srcs else ""),
           "count": len(unique), "area": cfg.get("area_name", "Thanet"), "jobs": unique}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"Apprenticeship board: {len(unique)} apprenticeships")


def classify(job, cfg, today):
    """Return (keep, reason, flags)."""
    text = f"{job['title']} . {job['description']}"
    if job["id"] in cfg.get("extra_block_ids", []):
        return False, "blocked id", {}
    forced = job["id"] in cfg.get("extra_allow_ids", [])

    for bad in cfg.get("exclude_places", []):
        if re.search(r"\b" + re.escape(bad) + r"\b", f"{job['location']} {job['title']}", re.I):
            return False, f"outside the commute area ({bad})", {}
    if not any(re.search(r"\b" + re.escape(p) + r"\b", job["location"], re.I) for p in cfg["allowed_places"]):
        return False, f"outside the commute area ({job['location'] or 'no location'})", {}
    mins = commute_minutes(job["location"], cfg)
    if cfg.get("commute") and (mins is None or mins > cfg["commute"].get("max_minutes", 90)):
        return False, f"over {cfg['commute'].get('max_minutes', 90)} min door to door ({job['location']})", {}
    closing = parse_date_iso(job["closing"])
    if job.get("closed_notice"):
        return False, "advert says closed", {}
    if not closing:
        return False, "no closing date (cannot prove it is open)", {}
    days_left = (closing - today).days
    if days_left < cfg.get("hide_when_days_left_below", 1):
        return False, f"expired / closing too soon ({job['closing']})", {}

    if not forced:
        emp = job["employer"].lower()
        for b in cfg.get("blocked_employers", []):
            if b.lower() in emp or b.lower() in job["title"].lower():
                return False, f"self-employed/blocked employer ({b})", {}
        hit = _any(SELF_EMPLOYED, f"{job['job_type']} . {text}")
        if hit:
            return False, f"self-employed ('{hit}')", {}
        hit = _any(SENIOR_TITLES, job["title"])
        if hit and not re.search(r"\b(?:trainee|apprentice|apprenticeship)\b", job["title"], re.I):
            return False, f"not entry level (title: '{hit}')", {}
        clean = text
        for p in NOT_NEEDED:
            clean = re.sub(p, " ", clean, flags=re.I)
        for pats, label in ((EXPERIENCE, "asks for experience"), (QUALIFICATION, "needs a qualification/licence")):
            hit = _any(pats + cfg.get("extra_reject_phrases", []), clean)
            if hit:
                return False, f"{label} ('{hit}')", {}
        nums = [float(n.replace(",", "")) for n in re.findall(r"£\s*([\d,]+(?:\.\d+)?)", job["pay"])]
        if nums and max(nums) > cfg.get("max_annual_salary_top", 45000):
            return False, f"pay range suggests commission/senior role ({job['pay']})", {}
        amin = annual_min(job["pay"])
        if amin and amin > cfg.get("max_annual_salary", 32000):
            return False, f"salary too high for entry level ({job['pay']})", {}
        if amin and ("nhs" in f"{job['employer']} {job['title']}".lower() or job.get("source") == "NHS Jobs") \
                and amin > cfg.get("nhs_max_annual_salary", 25500):
            return False, f"NHS Band 3+ pay - usually needs experience ({job['pay']})", {}

    flags = {
        "licence": needs_licence(job),
        "card": card_needed(clean if not forced else text),
        "no_experience": bool(_any(NO_EXPERIENCE, text)),
        "days_left": days_left,
        "travel_minutes": mins,
    }
    return True, "ok", flags


def parse_date_iso(s):
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def clean_title(t):
    t = re.split(r"\s*\|\|\s*", t)[0]
    t = t.split(" | ")[0]
    if "_" in t:
        t = t.split("_")[0]
    t = re.sub(r"^\d+\s*-\s*", "", t)                      # leading reference numbers
    t = re.sub(r"\s*\*+[^*]*\*+\s*", " ", t)                  # ** RELOCATION ** style shouting
    t = re.sub(r"\s*(?:P/T|F/T)?\s*@\s*£.*$", "", t, flags=re.I)  # "P/T@ £15/hr in X"
    t = re.sub(r"\s+-\s+(?:Canterbury|Folkestone|Kent|Thanet)\b.*$", "", t)
    t = re.sub(r"\s*\((?:TA|fixed[^)]*|temporary[^)]*|maternity[^)]*|permanent[^)]*)\)", "", t, flags=re.I)
    t = re.sub(r"\s+\d+\s*hrs?\b.*$", "", t, flags=re.I)
    t = re.sub(r"\s*-\s*(?:part[ -]time|full[ -]time|car required|flex(?:ible)? hours)\b", "", t, flags=re.I)
    t = re.sub(r"\s*-\s*£[\d.]+.*$", "", t)
    t = re.sub(r"\s+-\s+(?:QEQM|QEH|K&C|WHH)\b.*$", "", t)        # hospital site suffixes
    t = re.sub(r"\s*/+\s*", "/", t)
    t = re.sub(r"\s+", " ", t).strip(" -–")
    return t


def _money(x):
    v = float(x.replace(",", ""))
    return f"£{v:,.2f}" if v < 100 else f"£{v:,.0f}"


def tidy_pay(pay, description=""):
    """Short, TV-friendly pay text."""
    p = pay or ""
    m = re.search(r"actual\s*£\s*([\d,]+(?:\.\d+)?)", p, re.I)
    if m:
        return f"{_money(m.group(1))}/yr (part-time)"
    nums = re.findall(r"£\s*([\d,]+(?:\.\d+)?)", p)
    if nums:
        lo, hi = nums[0], nums[1] if len(nums) > 1 else nums[0]
        f_lo, f_hi = float(lo.replace(",", "")), float(hi.replace(",", ""))
        if (f_lo < 100) != (f_hi < 100):          # "£13.18 to £25,427" = hourly rate + yearly total: show the hourly rate
            hi = lo = (lo if f_lo < 100 else hi)
        elif f_hi < f_lo:
            if f_lo > 1000 and f_hi > 1000:       # schools: full-time figure first, then the actual part-time pay
                return f"{_money(hi)}/yr (part-time)"
            lo, hi = hi, lo                       # otherwise just put the range the right way round
        rng = _money(lo) if float(lo.replace(",", "")) == float(hi.replace(",", "")) else f"{_money(lo)}–{_money(hi)}"
        if re.search(r"a day|per day|daily", p, re.I):
            return f"{rng}/day"
        if re.search(r"hour|/hr|p/?h|per hr", p, re.I) or float(lo.replace(",", "")) < 100:
            if float(lo.replace(",", "")) < 7:       # e.g. "£3 night premium" - not the real wage (apprentice rates are ~£7.55+)
                return "See advert"
            return f"{rng}/hr"
        extra = " pro rata" if "pro rata" in p.lower() else ""
        return f"{rng}/yr{extra}"
    m = re.search(r"£\s*(\d+\.\d{2})\s*(?:per hour|an hour|p/?h|/hr|ph\b|hourly)", description, re.I)
    if m:
        return f"{_money(m.group(1))}/hr"
    if "national minimum" in p.lower():
        return "Minimum wage or above"
    if "apprentice minimum" in p.lower():
        return "Apprentice wage"
    return "See advert"


def tidy_employer(e):
    e = re.sub(r"\s+(?:limited|ltd\.?|plc|llp)$", "", e.strip(), flags=re.I)
    if e.lower() == "nhs jobs":
        return "NHS"
    if e.isupper() and " " in e:
        e = e.title()
    return e


# --------------------------------------------------------------------------- fetching
class Fetcher:
    def __init__(self, delay, dump=None):
        self.delay, self.dump = delay, dump
        if dump is None:
            import requests
            self.s = requests.Session()
            self.s.headers["User-Agent"] = UA

    def get(self, path):
        if self.dump is not None:
            if path not in self.dump:
                return 404, ""
            return 200, self.dump[path]
        for attempt in range(3):
            try:
                time.sleep(self.delay)
                r = self.s.get(BASE + path, timeout=30)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(10 * (attempt + 1))
                    continue
                return r.status_code, r.text
            except Exception as e:  # network hiccup
                print("  retry after error:", e)
                time.sleep(5 * (attempt + 1))
        return 0, ""


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dump", help="JSON file {path: html} for offline testing")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD) for testing")
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    com = cfg.get("commute")
    if com:   # the commute table decides which places count
        mx = com.get("max_minutes", 90)
        cfg["allowed_places"] = [p for p, m in {**com["towns"], **com["postcodes"]}.items() if m <= mx]
    dump = json.load(open(args.from_dump, encoding="utf-8")) if args.from_dump else None
    if dump is not None and "pages" in dump:      # file saved by the Work Hub collector bookmark
        print(f"Using collected file from {dump.get('collected')} ({dump.get('thanet')} Thanet adverts)")
        dump = dump["pages"]
    f = Fetcher(cfg.get("request_delay_seconds", 1.0), dump)
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()

    # Sources: official job feeds (Reed, Teaching Vacancies, NHS Jobs, Adzuna). Fully automatic.
    reed_jobs = None          # = jobs from the feeds (name kept for the code below)
    used, failed = [], []
    if dump is None:
        import sources
        places = cfg["allowed_places"]
        collected = []

        found_by = {}

        def run(name, fn):
            try:
                js = fn()
                collected.extend(js)
                used.append(name)
                found_by[name] = len(js)
            except Exception as e:      # one feed failing never stops the others
                print(f"!! {name} failed: {e}")
                failed.append(name)

        reed_key = os.environ.get("REED_API_KEY", "").strip()
        if reed_key:
            from reed_source import fetch
            run("Reed", lambda: [dict(j, id="reed:" + j["id"], source="Reed")
                                 for loc in cfg.get("search_locations", [cfg["search_location"]])
                                 for j in fetch(reed_key, loc, 10, places=places)])
        if cfg.get("use_teaching_vacancies", True):
            run("Teaching Vacancies", lambda: sources.teaching_vacancies(places))
        if cfg.get("use_nhs_jobs", True):
            run("NHS Jobs", lambda: [j for loc in cfg.get("search_locations", [cfg["search_location"]])
                                     for j in sources.nhs_jobs(places, loc, 10)])
        faa_key = os.environ.get("FAA_API_KEY", "").strip()
        if cfg.get("use_apprenticeships", True):     # official API if a key is saved, otherwise the public website
            run("Find an apprenticeship", (lambda: sources.apprenticeships(faa_key, places)) if faa_key
                else (lambda: sources.apprenticeships_site(places)))
        emp_cache_path = os.path.join(ROOT, "data", "employer_cache.json")
        try:
            emp_cache = json.load(open(emp_cache_path, encoding="utf-8"))
        except (OSError, ValueError):
            emp_cache = {}
        for emp in cfg.get("employers", []):
            if emp.get("enabled", True):
                run(emp["name"], lambda emp=emp: sources.employer_site(emp, places, today, emp_cache))
        os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
        with open(emp_cache_path, "w", encoding="utf-8") as fh:
            json.dump(emp_cache, fh, indent=0)
        az_id, az_key = os.environ.get("ADZUNA_APP_ID", "").strip(), os.environ.get("ADZUNA_APP_KEY", "").strip()
        if az_id and az_key and cfg.get("use_adzuna", True):
            run("Adzuna", lambda: [j for loc in cfg.get("search_locations", [cfg["search_location"]])
                                   for j in sources.adzuna(az_id, az_key, places, loc,
                                                           max_days_old=cfg.get("adzuna_max_days_old", 10))])
        write_health(found_by, failed, cfg, today)
        if not collected:
            print("No jobs from any feed. Keeping the previous jobs.json.")
            sys.exit(1)
        reed_jobs = collected

    # 1. collect job ids from the search results
    loc = cfg["search_location"]
    reed_by_id = {j["id"]: j for j in reed_jobs or []}
    ids, page, total = list(reed_by_id), 1, None
    while reed_jobs is None and page <= cfg.get("max_search_pages", 40):
        status, html = f.get(f"/jobs/search?location={loc}&pageNumber={page}")
        if status != 200:
            print(f"search page {page}: HTTP {status}, stopping")
            break
        found, t = parse_search(html)
        total = total or t
        new = [i for i in found if i not in ids]
        ids += new
        print(f"search page {page}: {len(found)} jobs ({len(ids)} so far of {total})")
        if not found or (total and page >= -(-total // 10)):
            break
        page += 1
    if not ids:
        print("No jobs found - site may be down or changed. Keeping the previous jobs.json.")
        sys.exit(1)

    # 2. open every advert and classify it
    # Cache: adverts we already rejected are not re-opened for 7 days (keeps the load on the
    # DWP site small). Jobs that ARE on the board are re-checked every run.
    cache_path = os.path.join(ROOT, "data", "cache.json")
    try:
        cache = json.load(open(cache_path)) if dump is None else {}
    except (OSError, ValueError):
        cache = {}
    kept, report, apprentices, careers = [], [], [], []
    for jid in ids:
        c = cache.get(jid)
        if c and c["reason"] != "ok" and not re.search(r"CSCS|forklift|flt|counterbalance", c["reason"], re.I) and (today - dt.date.fromisoformat(c["checked"])).days < 7:
            report.append((jid, c["title"], c["reason"] + " (cached)"))
            lvl = career_level(c["reason"])
            if lvl and reed_jobs is not None and not is_apprenticeship(reed_by_id[jid]) and still_open(reed_by_id[jid], today, cfg):
                careers.append(career_entry(jid, reed_by_id[jid], cfg, lvl))
            elif c["reason"] == NO_DATE and reed_jobs is not None and not is_apprenticeship(reed_by_id[jid]):
                e = undated_entry(jid, reed_by_id[jid], cfg, today)
                if e:
                    careers.append(e)
            if reed_jobs is not None and is_apprenticeship(reed_by_id[jid]):     # may still suit the apprenticeship board
                ok, why, aflags = classify_apprenticeship(reed_by_id[jid], cfg, today)
                if ok:
                    apprentices.append(board_entry(jid, reed_by_id[jid], cfg, aflags))
            continue
        if reed_jobs is not None:
            job = reed_by_id[jid]
        else:
            status, html = f.get(f"/jobs/{jid}")
            if status != 200:
                if dump is None:
                    report.append((jid, "", f"advert not available (HTTP {status})"))
                continue                       # collector only opens Thanet adverts
            job = parse_detail(html, jid)
        keep, reason, flags = classify(job, cfg, today)
        report.append((jid, job["title"], reason))
        if not reason.startswith("expired"):
            cache[jid] = {"title": job["title"], "reason": reason, "checked": str(today)}
        if keep and not is_apprenticeship(job):       # apprenticeships have their own board and video
            kept.append(board_entry(jid, job, cfg, flags))
        elif career_level(reason) and not is_apprenticeship(job):   # experienced roles: careers side only
            careers.append(career_entry(jid, job, cfg, career_level(reason)))
        elif reason == NO_DATE and not is_apprenticeship(job):        # open today, but no closing date
            e = undated_entry(jid, job, cfg, today)
            if e:
                careers.append(e)
        if reed_jobs is not None and is_apprenticeship(job):
            ok, why, aflags = classify_apprenticeship(job, cfg, today)
            if ok:
                apprentices.append(board_entry(jid, job, cfg, aflags))

    if failed:
        try:
            prev = json.load(open(os.path.join(ROOT, "docs", "jobs.json"), encoding="utf-8"))
            carried = [j for j in prev.get("jobs", []) if j.get("source") in failed and j.get("closing", "") > str(today)]
            kept += carried
            print(f"Kept {len(carried)} jobs from yesterday for feeds that failed today: {', '.join(failed)}")
        except (OSError, ValueError):
            pass
    kept.sort(key=lambda j: (j.get("closing_estimated", False), j["closing"], j["title"]))
    seen_keys, unique = set(), []
    for j in kept:
        k = (re.sub(r"[^a-z0-9]", "", j["title"].lower()), j["town"].lower())
        if k not in seen_keys:
            seen_keys.add(k)
            unique.append(j)
    kept = sorted(unique, key=lambda j: (j["closing"], j["title"]))
    out = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": (", ".join(used + [f + " (yesterday's)" for f in failed]) +
                   (". Teaching Vacancies, NHS Jobs and Find an apprenticeship data under the Open Government Licence v3.0" if used else "")
                   if reed_jobs is not None else
                   "DWP Find a Job (jobs.service.gov.uk) - contains public sector information licensed under the Open Government Licence v3.0"),
        "count": len(kept),
        "area": cfg.get("area_name", "Thanet"),
        "jobs": kept,
    }
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "jobs.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    if reed_jobs is not None:
        write_apprenticeships(apprentices, failed, used, cfg, today)
        write_careers(careers, failed, used, cfg, today)
    write_go_index(today)
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    cache = {k: v for k, v in cache.items() if k in ids}          # forget adverts that have gone
    if dump is None:
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=0)
    with open(os.path.join(ROOT, "data", "report.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"Run {out['generated']}  kept {len(kept)} of {len(ids)}\n\n")
        for jid, title, reason in sorted(report, key=lambda r: (r[2] != "ok", r[2])):
            link = reed_by_id[jid]["url"] if jid in reed_by_id else f"{BASE}/jobs/{jid}"
            fh.write(f"{'KEEP' if reason == 'ok' else 'SKIP'} | {title[:60]:60} | {reason} | {link}\n")
    print(f"Done: {len(kept)} jobs on the board (checked {len(ids)}). See data/report.txt for why others were skipped.")


if __name__ == "__main__":
    main()
