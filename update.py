#!/usr/bin/env python3
"""Pull Street Fighter League seasons (US/Americas, Japan, Europe/EMEAA) from Liquipedia and write data.js.

Run:  python3 update.py          # refetch each league's newest season, reuse cached older ones
      python3 update.py --all    # refetch everything
      python3 update.py --league us   # refetch only that league's newest season (others from cache)

Uses the public MediaWiki API (gzip required, a few seconds between requests).
Raw wikitext is cached in ./cache so older seasons are only downloaded once.
"""
import gzip, json, re, sys, time, urllib.request, urllib.parse
from collections import Counter
from pathlib import Path

API = "https://liquipedia.net/fighters/api.php"
UA = "SFLStatsApp/1.0 (personal stats viewer)"
HERE = Path(__file__).parent
CACHE = HERE / "cache"
OUT = HERE / "data.js"
DELAY = 3

LEAGUES = {"us": "US / Americas", "jp": "Japan", "eu": "Europe / EMEAA"}
SFL = "Street_Fighter_League/"


def S(league, year, path, name, game="SF6", **extra):
    return {"league": league, "year": year, "path": SFL + path, "name": name, "game": game, **extra}


# Newest first within each league; each league's newest season is always refetched.
# extra=[(subpage, stage, phase label)] adds pages beyond Regular_Season/Playoffs.
# bracket_names overrides round names for brackets that don't count back from a final.
SEASONS = [
    S("us", 2026, "Americas/2026", "Pro-Americas 2026"),
    S("us", 2025, "United_States/2025", "Pro-US 2025"),
    S("us", 2024, "United_States/2024", "Pro-US 2024"),
    S("us", 2023, "United_States/2023", "Pro-US 2023"),
    S("us", 2022, "United_States/2022", "Pro-US 2022", "SFV"),
    S("jp", 2026, "Japan/2026", "Pro-JP 2026"),
    S("jp", 2025, "Japan/2025", "Pro-JP 2025"),
    S("jp", 2024, "Japan/2024", "Pro-JP 2024"),
    S("jp", 2023, "Japan/2023", "Pro-JP 2023", first_phase="First Stage",
      extra=[("Second_Stage", "Regular Season", "Second Stage")]),
    S("jp", 2022, "Japan/2022", "Pro-JP 2022", "SFV",
      extra=[("Grand_Finals", "Playoffs", None)],
      bracket_names={"Playoffs": {"R2M1": "Winners Final", "R1M1": "Losers Quarterfinal", "R2M2": "Losers Final"}}),
    S("eu", 2026, "EMEAA/2026", "Pro-EMEAA 2026"),
    S("eu", 2025, "Europe/2025", "Pro-Europe 2025"),
    S("eu", 2024, "Europe/2024", "Pro-Europe 2024"),
    S("eu", 2023, "Europe/2023", "Pro-Europe 2023"),
    S("eu", 2022, "Europe/2022", "Pro-Europe 2022", "SFV"),
]
DEFAULT_POINTS = {1: 10, 2: 10, 3: 20, 4: 10}
# Same organisation written differently across seasons (merged so career/all-time views line up).
TEAM_ALIASES = {
    "Red Rooster Team": "Red Rooster", "Bandits Gaming": "Bandits",
    # Japan 2022 match listings use short tags.
    "Nagoya NTPOJA": "Nagoya OJA",
    "G8S": "Good 8 Squad", "SSK": "Saishunkan Sol Kumamoto", "SNB": "Shinobism Gaming",
}
SLOT_LABELS = {"1st Match": 1, "2nd Match": 2, "3rd Match": 3, "Tie Breaker": 4}
CHAR_NAMES = {
    "ed": "Ed", "deejay": "Dee Jay", "bison": "M. Bison", "mbison": "M. Bison", "ehonda": "E. Honda",
    "honda": "E. Honda", "chunli": "Chun-Li", "aki": "A.K.I.", "cviper": "C. Viper", "jp": "JP",
    "g": "G", "fang": "F.A.N.G", "kage": "Kage", "zeku": "Zeku",
}

_last = [0.0]


def api(params):
    wait = DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    q = urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    _last[0] = time.time()
    return json.loads(raw)


def page(title, refresh):
    CACHE.mkdir(exist_ok=True)
    f = CACHE / (title.replace("/", "__") + ".txt")
    if f.exists() and not refresh:
        return f.read_text()
    print(f"  fetching {title}")
    d = api({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "titles": title})
    p = next(iter(d["query"]["pages"].values()))
    text = p["revisions"][0]["slots"]["main"]["*"] if "revisions" in p else ""
    f.write_text(text)
    return text


# ---------- wikitext helpers ----------

def block_at(text, start):
    """Return the balanced {{...}} template starting at text[start]."""
    depth, i = 0, start
    while i < len(text) - 1:
        two = text[i:i + 2]
        if two == "{{":
            depth += 1; i += 2; continue
        if two == "}}":
            depth -= 1; i += 2
            if depth == 0:
                return text[start:i]
            continue
        i += 1
    return text[start:]


def field(block, name):
    m = re.search(r"\|\s*" + re.escape(name) + r"\s*=\s*([^|}\n]*)", block)
    return m.group(1).strip() if m else ""


def clean_name(s):
    return re.sub(r"\s+", " ", s.replace("_", " ")).strip()


def char_name(slug):
    s = slug.strip().lower().replace(" ", "").replace(".", "").replace("-", "")
    return CHAR_NAMES.get(s, slug.strip().title())


def parse_map(mb, idx, points):
    chars = []
    for side in ("o1p1", "o2p1"):
        m = re.search(side + r"\s*=\s*\{\{Chars\|([^}]*)\}\}", mb)
        chars.append([char_name(x) for x in m.group(1).split("|") if x.strip()] if m else [])
    flat = re.sub(r"\{\{Chars\|[^}]*\}\}", "", mb)
    p1, p2 = clean_name(field(flat, "t1p1")), clean_name(field(flat, "t2p1"))
    s1, s2 = field(flat, "score1"), field(flat, "score2")
    w = field(flat, "winner")
    if not (p1 and p2 and s1.isdigit() and s2.isdigit()):
        # Keep a game whose winner is known even if Liquipedia lacks the other player
        # (the missing player is stored as "" and left out of player stats).
        if w in ("1", "2") and (p1, p2)[int(w) - 1] and (s1, s2)[int(w) - 1].isdigit():
            s1, s2 = (s1 if s1.isdigit() else "0"), (s2 if s2.isdigit() else "0")
        else:
            return None
    s1, s2 = int(s1), int(s2)
    win = 0 if s1 > s2 else 1 if s2 > s1 else (int(w) - 1 if w in ("1", "2") else 0)
    return {"n": idx, "pts": points.get(idx, 10), "p": [p1, p2], "c": chars, "s": [s1, s2], "w": win}


def parse_match(block, points):
    ops = []
    for om in re.finditer(r"\|\s*opponent([12])\s*=\s*\{\{TeamOpponent\|?([^}]*)\}\}", block):
        # Parameters come in any order: a positional team name plus named ones like score=.
        args = [x.strip() for x in om.group(2).split("|")]
        name = next((x for x in args if "=" not in x), "")
        score = next((x.split("=", 1)[1].strip() for x in args if x.startswith("score")), "")
        ops.append((om.group(1), name, score))
    ops = sorted(ops)[:2]  # some pages list opponent2 before opponent1
    if len(ops) < 2 or [o[0] for o in ops] != ["1", "2"]:
        return None
    teams = [clean_name(ops[0][1]), clean_name(ops[1][1])]
    listed = [ops[0][2].strip(), ops[1][2].strip()]
    maps = []
    for m in re.finditer(r"\|\s*map(\d+)\s*=\s*(?=\{\{Map)", block):
        mp = parse_map(block_at(block, m.end()), int(m.group(1)), points)
        if mp:
            maps.append(mp)
    # Match-level winner only (each map also has its own winner= field).
    outer = block
    for mm in reversed(list(re.finditer(r"\|\s*map\d+\s*=\s*(?=\{\{Map)", block))):
        outer = outer[:mm.start()] + outer[mm.end() + len(block_at(block, mm.end())):]
    winner = field(outer, "winner")
    return {"t": teams, "listed": listed, "maps": maps, "date": field(block, "date"), "winner": winner}


def heading_name(h):
    h = re.sub(r"\{\{HiddenSort\|([^}]*)\}\}", r"\1", h)
    return h.strip(" =")


def walk_matches(text, points):
    """Yield (round_name, match, bracket_key, section) for every {{Match}} in reading order."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    tokens = re.finditer(r"(?m)^(=+[^\n]+=+)\s*$|\{\{Matchlist[^\n]*|(\|\s*(R\d+M\d+)\s*=\s*)?\{\{Match\b", text)
    heading, title, section = "", "", ""
    for t in tokens:
        if t.group(1):
            heading, title = heading_name(t.group(1)), ""
            if len(t.group(1)) - len(t.group(1).lstrip("=")) <= 3:
                section = heading
        elif t.group(0).startswith("{{Matchlist"):
            m = re.search(r"title=([^|]*)", t.group(0))
            title = re.sub(r"\s+Matches$", "", m.group(1).strip()) if m else ""
        else:
            start = t.start() + (len(t.group(2)) if t.group(2) else 0)
            m = parse_match(block_at(text, start), points)
            if m:
                yield (title or heading), m, t.group(3), section


def format_points(overview):
    pts = dict(DEFAULT_POINTS)
    for label, n in SLOT_LABELS.items():
        m = re.search(r"\|\s*" + label + r"\s*\|\|[^\n]*\|\|\s*\+(\d+)\s*PTS", overview)
        if m:
            pts[n] = int(m.group(1))
    return pts


def series_targets(overview):
    """Points needed to win a playoff series, per round, from the format section."""
    t = {}
    m = re.search(r"Quarterfinals and Semifinals are First to (\d+) points", overview)
    if m:
        t["Quarterfinals"] = t["Semifinals"] = int(m.group(1))
    m = re.search(r"All matches are First to (\d+) points", overview)   # Japan division playoffs
    if m:
        t.setdefault("Quarterfinals", int(m.group(1)))
        t.setdefault("Semifinals", int(m.group(1)))
    m = re.search(r"Grand Finals is First to (\d+) points", overview)
    if m:
        t["Grand Finals"] = int(m.group(1))
    return t


def rosters(overview):
    out = {}
    for m in re.finditer(r"\{\{Opponent\|([^\n]*)\n\s*\|players=\{\{Persons(.*?)\n\s*\}\}", overview, re.S):
        ps = []
        for pm in re.finditer(r"\{\{Person\|([^|}]*)([^}]*)\}\}", m.group(2)):
            link = re.search(r"link=([^|}]*)", pm.group(2))
            ps.append((clean_name(pm.group(1)), clean_name(link.group(1)) if link else ""))
        out[clean_name(m.group(1))] = ps
    for i in [m.start() for m in re.finditer(r"\{\{TeamCard\s*\n", overview)]:
        b = block_at(overview, i)
        team = field(b, "team")
        if not team:
            continue
        ps = []
        for n in range(1, 9):
            name = field(b, f"p{n}")
            if name:
                ps.append((clean_name(name), clean_name(field(b, f"p{n}link"))))
        out[clean_name(team)] = ps
    return {TEAM_ALIASES.get(t, t): ps for t, ps in out.items()}


def norm_team(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def team_resolver(match_names):
    """Map every spelling of a team in one season to one name.

    The names used in match listings win (rosters sometimes add sponsors, e.g.
    "Hiroshima TEAM iXA" vs "TEAM iXA"); the most common spelling is kept.
    """
    canon = []
    for n, _ in Counter(TEAM_ALIASES.get(x, x) for x in match_names if x).most_common():
        if not any(related(n, c) for c in canon):
            canon.append(n)

    def resolve(name):
        name = TEAM_ALIASES.get(name, name)
        if not norm_team(name):
            return ""
        for c in canon:
            if norm_team(c) == norm_team(name):
                return c
        for c in canon:
            if related(name, c):
                return c
        return name
    return resolve


def related(a, b):
    a, b = norm_team(a), norm_team(b)
    return a == b or (min(len(a), len(b)) >= 3 and (a in b or b in a))


def round_names(keys):
    """Bracket rounds R1..Rn → names counted back from the final."""
    names = ["Grand Finals", "Semifinals", "Quarterfinals", "Round of 16"]
    rmax = max(int(re.match(r"R(\d+)", k).group(1)) for k in keys)
    return {r: names[rmax - r] if rmax - r < len(names) else f"Round {r}" for r in range(1, rmax + 1)}


def build_season(cfg, refresh):
    path, name = cfg["path"], cfg["name"]
    sid = f"{cfg['league']}-{cfg['year']}"
    print(f"{name}:")
    overview = page(path, refresh)
    pages = [("Regular_Season", "Regular Season", cfg.get("first_phase"))] + cfg.get("extra", []) + [("Playoffs", "Playoffs", None)]
    texts = {sub: page(path + "/" + sub, refresh) for sub, _, _ in pages}
    rs = texts["Regular_Season"]
    points = format_points(overview)
    match_names = [clean_name(x) for txt in texts.values() for x in re.findall(r"TeamOpponent\|(?:score=[^|}]*\|)?([^|}=]+)", txt)]
    resolve = team_resolver(match_names)
    roster = {}
    for t, ps in rosters(overview).items():
        roster.setdefault(resolve(t), ps)

    battles, seen = [], set()

    def add(stage, rnd, m, phase=None, div=None):
        if not m["maps"]:
            return
        t = [resolve(x) for x in m["t"]]
        sig = (tuple(t), tuple((tuple(x["p"]), tuple(x["s"])) for x in m["maps"]))
        if sig in seen:
            return
        seen.add(sig)
        score = [0, 0]
        for mp in m["maps"]:
            score[mp["w"]] += mp["pts"]
        sets = [sum(mp["w"] == i for mp in m["maps"]) for i in (0, 1)]
        listed = [int(x) for x in m["listed"]] if all(x.isdigit() for x in m["listed"]) else None
        # Older pages list sets won (e.g. 2-1) instead of points; accept either.
        if stage == "Regular Season" and listed and listed != score and listed != sets:
            print(f"  ! score mismatch {name} {rnd} {t}: listed {m['listed']}, computed {score}; "
                  + "; ".join(f"M{x['n']} {x['p'][0]} {x['s'][0]}-{x['s'][1]} {x['p'][1]}" for x in m["maps"]), file=sys.stderr)
        b = {"stage": stage, "round": rnd, "date": m["date"], "t": t, "score": score, "maps": m["maps"]}
        if phase:
            b["phase"] = phase
            b["round"] = f"{phase} · {rnd}"
        if div:
            b["div"] = div
        battles.append(b)

    bracket = []
    for sub, stage, phase in pages:
        items = list(walk_matches(texts[sub], points))
        if stage == "Regular Season":
            for rnd, m, _, section in items:
                div = section if re.match(r"(Division|Group|Conference)\b", section) else None
                add(stage, rnd or "Regular Season", m, phase, div)
            continue
        # Playoffs: bracket matches give the overall result; details/bracket maps give the games.
        override = cfg.get("bracket_names", {}).get(sub, {})
        keys = [k for _, _, k, _ in items if k]
        rnames = round_names(keys) if keys else {}
        # Detail sections name rounds slightly differently from the bracket ("Grand Final" vs
        # "Grand Finals"), so games take the round of the bracket series with the same two teams.
        series_round = {}
        for rnd, m, key, _ in items:
            if key:
                series_round[frozenset(resolve(x) for x in m["t"])] = override.get(key) or rnames[int(re.match(r"R(\d+)", key).group(1))]
        for rnd, m, key, _ in items:
            if not key:
                add(stage, series_round.get(frozenset(resolve(x) for x in m["t"]), rnd), m)
                continue
            r = override.get(key) or rnames[int(re.match(r"R(\d+)", key).group(1))]
            t = [resolve(x) for x in m["t"]]
            sc = [int(x) if x.isdigit() else None for x in m["listed"]]
            win = None
            if None not in sc and sc[0] != sc[1]:
                win = 0 if sc[0] > sc[1] else 1
            elif m["winner"] in ("1", "2"):
                win = int(m["winner"]) - 1
            elif m["maps"]:
                pts = [sum(x["pts"] for x in m["maps"] if x["w"] == i) for i in (0, 1)]
                win = 0 if pts[0] > pts[1] else 1
            if any(t):
                bracket.append({"round": r, "t": t, "score": sc, "w": win})
            add(stage, r, m)

    champion = None
    gf = [b for b in bracket if b["round"] == "Grand Finals" and b["w"] is not None]
    if gf:
        champion = gf[-1]["t"][gf[-1]["w"]]

    order = [resolve(clean_name(t)) for t in re.findall(r"\|\{\{TeamOpponent\|([^}|]*)\}\}\s*\n", rs.split("<!-- Rounds")[0])]
    teams = [t for t in dict.fromkeys(order + list(roster)) if t]
    rs_n = sum(b["stage"] == "Regular Season" for b in battles)
    divs = {}
    for b in battles:
        if b.get("div"):
            for t in b["t"]:
                divs.setdefault(b["div"], set()).add(t)
    print(f"  {rs_n} regular-season battles, {len(battles) - rs_n} playoff battles, champion: {champion or '—'}"
          + (f", divisions: {', '.join(divs)}" if divs else ""))
    unknown = {t for b in battles for t in b["t"] if t not in roster}
    if unknown:
        print(f"  ! {name}: teams not on roster list: {unknown}", file=sys.stderr)
    return {
        "id": sid, "league": cfg["league"], "year": cfg["year"], "name": name, "game": cfg["game"],
        "divisions": {d: sorted(ts) for d, ts in divs.items()},
        "phases": [p for p in dict.fromkeys(ph for _, st, ph in pages if st == "Regular Season") if p],
        "source": "https://liquipedia.net/fighters/" + path,
        "points": points, "teams": teams, "targets": series_targets(overview),
        "rosters": {t: [p for p, _ in ps] for t, ps in roster.items()},
        "links": {p: l for ps in roster.values() for p, l in ps if l},
        "battles": battles, "bracket": bracket, "champion": champion,
    }


def unify_players(seasons):
    """Give each person one name across seasons, using Liquipedia redirects + roster links."""
    def names_in(s):
        for b in s["battles"]:
            for m in b["maps"]:
                yield from m["p"]
        for ps in s["rosters"].values():
            yield from ps

    page_for = {}  # (season, name) -> page title to look up
    for s in seasons:
        for n in set(names_in(s)) - {""}:
            page_for[(s["id"], n)] = s["links"].get(n) or n
    titles = sorted(set(page_for.values()))
    # Name lookups are saved between runs; only new names hit the API.
    names_file = CACHE / "_player_pages.json"
    known = json.loads(names_file.read_text()) if names_file.exists() else {}
    resolved = {t: known[t] for t in titles if t in known}
    todo = [t for t in titles if t not in known]
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        d = api({"action": "query", "titles": "|".join(chunk), "redirects": 1})["query"]
        m = {x["from"]: x["to"] for x in d.get("normalized", [])}
        r = {x["from"]: x["to"] for x in d.get("redirects", [])}
        missing = {p["title"] for p in d["pages"].values() if "missing" in p}
        for t in chunk:
            a = m.get(t, t)
            b = r.get(a, a)
            resolved[t] = (b if a not in missing and b not in missing else t).lower()
    names_file.write_text(json.dumps({**known, **resolved}, ensure_ascii=False, indent=0, sort_keys=True))
    # Display name = how the person was written in the newest season they played.
    display = {}
    for s in seasons:  # newest first
        for n in names_in(s):
            if not n:
                continue
            key = resolved[page_for[(s["id"], n)]]
            display.setdefault(key, n)
    rename = {k: display[resolved[t]] for k, t in page_for.items()}
    rename.update({(s["id"], ""): "" for s in seasons})
    for s in seasons:
        sid = s["id"]
        for b in s["battles"]:
            for m in b["maps"]:
                m["p"] = [rename[(sid, p)] for p in m["p"]]
        s["rosters"] = {t: [rename[(sid, p)] for p in ps] for t, ps in s["rosters"].items()}
        del s["links"]
    merged = {}
    for (sid, n), new in rename.items():
        if n != new:
            merged.setdefault(new, set()).add(n)
    for new, olds in sorted(merged.items()):
        print(f"  same player: {', '.join(sorted(olds))} → {new}")


def unify_team_case(seasons):
    """Same team written differently across seasons → its most common spelling.

    Also drops Liquipedia disambiguation like "AEGIS (French team)".
    """
    strip = lambda t: re.sub(r"\s*\([^)]*\)\s*$", "", t)
    counts = {}
    for s in seasons:
        for t in [t for b in s["battles"] for t in b["t"]] + list(s["rosters"]):
            if t:
                counts.setdefault(norm_team(strip(t)), Counter())[strip(t)] += 1
    spelling = {k: c.most_common(1)[0][0] for k, c in counts.items()}
    fix = lambda t: spelling.get(norm_team(strip(t)), strip(t)) if t else t
    for s in seasons:
        for b in s["battles"]:
            b["t"] = [fix(t) for t in b["t"]]
        for b in s["bracket"]:
            b["t"] = [fix(t) for t in b["t"]]
        s["rosters"] = {fix(t): ps for t, ps in s["rosters"].items()}
        s["teams"] = list(dict.fromkeys(fix(t) for t in s["teams"]))
        s["divisions"] = {d: sorted({fix(t) for t in ts}) for d, ts in s["divisions"].items()}
        s["champion"] = fix(s["champion"])


def main():
    refresh_all = "--all" in sys.argv
    only = sys.argv[sys.argv.index("--league") + 1] if "--league" in sys.argv else None
    newest = {}
    for cfg in SEASONS:
        newest.setdefault(cfg["league"], cfg["year"])
    seasons = [build_season(cfg, refresh=refresh_all or (cfg["year"] == newest[cfg["league"]] and only in (None, cfg["league"]))) for cfg in SEASONS]
    unify_team_case(seasons)
    print("Matching player names across seasons…")
    # Newest seasons first so each player keeps the tag they use now.
    unify_players(sorted(seasons, key=lambda s: -s["year"]))
    data = {"updated": time.strftime("%Y-%m-%d %H:%M"), "leagues": LEAGUES, "seasons": seasons}
    OUT.write_text("window.SFL = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(f"Wrote {OUT.name} ({OUT.stat().st_size // 1024} KB).")


if __name__ == "__main__":
    main()
