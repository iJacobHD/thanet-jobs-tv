"""
One-off coverage check (uses at most MAX_CALLS Adzuna calls - the free key has very few).
Pulls local jobs from Adzuna, compares them with everything we already have (board, careers, apprenticeships)
and writes data/adzuna_check.txt: how many we already cover, and which employers we are missing.
"""
import collections, json, os, re, sys, time
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_CALLS = int(os.environ.get("MAX_CALLS", 8))
sys.path.insert(0, os.path.dirname(__file__))
import sources  # noqa: E402

app_id, app_key = os.environ.get("ADZUNA_APP_ID", "").strip(), os.environ.get("ADZUNA_APP_KEY", "").strip()
if not (app_id and app_key):
    sys.exit("Add ADZUNA_APP_ID and ADZUNA_APP_KEY as GitHub secrets first.")
cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
places = cfg["allowed_places"]

def norm(t):
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", (t or "").lower())
    return " ".join(w for w in re.findall(r"[a-z]+", t) if w not in {"the", "and", "of", "a", "in", "at", "to", "for", "ltd", "limited", "uk", "plc", "group"})

ours = []
for f in ("jobs.json", "careers.json", "apprenticeships.json"):
    try:
        ours += json.load(open(os.path.join(ROOT, "docs", f), encoding="utf-8")).get("jobs", [])
    except (OSError, ValueError):
        pass
our_keys = {(norm(j["title"]), norm(j.get("employer", ""))) for j in ours}
our_titles = collections.defaultdict(set)
for j in ours:
    our_titles[norm(j["title"])].add(norm(j.get("employer", "")))

calls, got = 0, []
s = requests.Session(); s.headers.update(sources.UA)
for page in range(1, MAX_CALLS + 1):
    r = s.get(f"https://api.adzuna.com/v1/api/jobs/gb/search/{page}", params={
        "app_id": app_id, "app_key": app_key, "where": "Margate", "distance": 40,
        "results_per_page": 50, "content-type": "application/json"}, timeout=30)
    calls += 1
    if r.status_code != 200:
        print("Adzuna said:", r.status_code, r.text[:200]); break
    res = r.json().get("results", [])
    for v in res:
        loc = (v.get("location") or {}).get("display_name", "") + " " + " ".join((v.get("location") or {}).get("area") or [])
        if sources._thanet(loc, places):
            got.append({"title": v.get("title", ""), "employer": (v.get("company") or {}).get("display_name", ""), "where": loc.strip()})
    if len(res) < 50:
        break
    time.sleep(2)

def have(j):
    t, e = norm(j["title"]), norm(j["employer"])
    if (t, e) in our_keys:
        return True
    return any(e and (e in oe or oe in e) for oe in our_titles.get(t, ()))   # same title, similar employer

hit = [j for j in got if have(j)]
miss = [j for j in got if not have(j)]
emp = collections.Counter(j["employer"] or "(not named)" for j in miss)
out = [f"Adzuna coverage check - {time.strftime('%Y-%m-%d %H:%M')} UTC - used {calls} of the key's calls",
       f"Local jobs from Adzuna: {len(got)}",
       f"Already on our board or Pathway: {len(hit)} ({round(100 * len(hit) / max(1, len(got)))}%)",
       f"Missing: {len(miss)}", "", "Employers we are missing most often:"]
out += [f"  {n:>3}  {e}" for e, n in emp.most_common(40)]
out += ["", "Sample of missing jobs:"] + [f"  - {j['title']} | {j['employer']} | {j['where']}" for j in miss[:80]]
open(os.path.join(ROOT, "data", "adzuna_check.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("\n".join(out[:8]))
