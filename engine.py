"""AgentShelf engine: audit a listing, simulate AI shopping agents choosing from a shelf,
and rewrite the listing so agents pick it more often.

Two modes:
  * LLM mode   - Claude plays the shopping agent and the copywriter (needs ANTHROPIC_API_KEY)
  * Proxy mode - a transparent, deterministic scoring agent, so the demo runs with no key
"""
from __future__ import annotations

import math
import random
import re
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------------------
STOP = set("""a an the and or for with of to in on at by from is are be this that it its your you
my me i we our need want find get buy something some about around least than up as so
should must has have will can also both all any into without no not very only just please
like would could which who what when where how one two""".split())

FLUFF = ["best", "premium", "amazing", "perfect", "ultimate", "high quality", "top quality",
         "#1", "number one", "incredible", "awesome", "revolutionary", "world's", "unbeatable",
         "superior", "luxury", "must-have", "100% satisfaction", "life-changing", "hottest",
         "excellent", "great gift", "perfect gift", "upgraded", "newest", "best seller"]

UNIT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:-|to)?\s?\d*(?:[.,]\d+)?\s?"
    r"(?:sq\.?\s?ft|square feet|ft|feet|inch(?:es)?|in\b|\"|cm|mm|m\b|lbs?|pounds?|kg|g\b|oz|"
    r"mah|v\b|volts?|w\b|watts?|db|hours?|hrs?|mins?|minutes?|days?|years?|months?|"
    r"gb|tb|mb/s|gb/s|mbps|hz|l\b|liters?|litres?|ml|cfm|cadr|mph|pcs|pack|count|sounds?|"
    r"levels?|modes?|speeds?|%)",
    re.I)

ATTR_CHECKS = {
    "dimensions_or_size": re.compile(r"\b(dimension|size|inch|inches|cm|mm|fits|sq\.?\s?ft|liters?|capacity)\b", re.I),
    "weight": re.compile(r"\b(weigh|weight|lbs?|pounds?|kg|ounces?|oz)\b", re.I),
    "materials": re.compile(r"\b(material|made of|made from|cotton|polyester|nylon|plastic|steel|aluminum|abs|silicone|leather|mesh|fabric)\b", re.I),
    "compatibility_or_use": re.compile(r"\b(compatible|works with|fits|designed for|ideal for|suitable for|for use with|supports)\b", re.I),
    "warranty_or_returns": re.compile(r"\b(warranty|guarantee|return|refund)\b", re.I),
    "certification_or_safety": re.compile(r"\b(certified|certification|ul\b|etl|fcc|fda|cpsc|bpa[- ]free|ozone[- ]free|carb|energy star|safety|safe|non-toxic|iso|hip[- ]healthy)\b", re.I),
    "whats_included": re.compile(r"\b(includes?|included|in the box|package contains|comes with|set of)\b", re.I),
}
ATTR_LABELS = {
    "dimensions_or_size": "Size / dimensions / capacity",
    "weight": "Weight",
    "materials": "Materials",
    "compatibility_or_use": "Compatibility / who it is for",
    "warranty_or_returns": "Warranty / returns",
    "certification_or_safety": "Certifications / safety",
    "whats_included": "What's in the box",
}

FEATURE_LABELS = {
    "query_coverage": "Share of the shopper's words found in title + bullets",
    "title_coverage": "Share of the shopper's words found in the title",
    "n_specs": "Number of measurable specs (numbers with units)",
    "n_bullets": "Number of bullet points",
    "desc_words": "Description length (words)",
    "title_words": "Title length (words)",
    "fluff_per_100": "Marketing fluff words per 100 words",
    "attr_coverage": "Share of key attributes stated (size, materials, warranty, ...)",
}


def tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9\-\.]*", (text or "").lower()) if t not in STOP and len(t) > 1]


def stem(t: str) -> str:
    for suf in ("ing", "ers", "es", "s"):
        if len(t) > 4 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def full_text(lst: dict) -> str:
    attrs = " ".join(f"{k}: {v}" for k, v in (lst.get("attributes") or {}).items())
    return " \n".join([lst.get("title", ""), lst.get("brand", ""), " ".join(lst.get("bullets", [])),
                       lst.get("description", ""), attrs, lst.get("price", "") or ""])


# --------------------------------------------------------------------------------------
# Features + audit (deterministic, grounded in the ESCI analysis)
# --------------------------------------------------------------------------------------
def listing_features(lst: dict, query: str) -> dict:
    title = lst.get("title", "")
    body = " ".join(lst.get("bullets", [])) + " " + " ".join(f"{k} {v}" for k, v in (lst.get("attributes") or {}).items())
    text = full_text(lst)
    q = {stem(t) for t in tokens(query)}
    tb = {stem(t) for t in tokens(title + " " + body)}
    tt = {stem(t) for t in tokens(title)}
    words = max(1, len(text.split()))
    low = text.lower()
    fluff = sum(low.count(f) for f in FLUFF)
    attrs = sum(1 for rx in ATTR_CHECKS.values() if rx.search(text))
    return {
        "query_coverage": len(q & tb) / len(q) if q else 0.0,
        "title_coverage": len(q & tt) / len(q) if q else 0.0,
        "n_specs": len(UNIT_RE.findall(text)),
        "n_bullets": len(lst.get("bullets", [])),
        "desc_words": len((lst.get("description") or "").split()),
        "title_words": len(title.split()),
        "fluff_per_100": 100 * fluff / words,
        "attr_coverage": attrs / len(ATTR_CHECKS),
    }


def audit(lst: dict, market: dict) -> dict:
    """Agent-readiness score 0-100 plus concrete issues. Uses all the market's shopper requests
    as 'query' so coverage reflects what real agents will be asked."""
    intents = [market["query"]] + market["intents"]
    covs = [listing_features(lst, q)["query_coverage"] for q in intents]
    f = listing_features(lst, market["query"])
    f["intent_coverage"] = sum(covs) / len(covs)
    text = full_text(lst)

    parts = {
        "Matches what shoppers ask for": min(1.0, f["intent_coverage"] / 0.6) * 25,
        "Measurable specs": min(1.0, f["n_specs"] / 10) * 20,
        "Key attributes stated": f["attr_coverage"] * 20,
        "Structure (title, 5 bullets, description)": (min(1, f["n_bullets"] / 5) * 0.5 + min(1, f["desc_words"] / 60) * 0.3 + (0.2 if 8 <= f["title_words"] <= 30 else 0.05)) * 20,
        "Facts over fluff": max(0.0, 1 - f["fluff_per_100"] / 3) * 15,
    }
    score = round(sum(parts.values()))

    issues = []
    missing_attrs = [ATTR_LABELS[k] for k, rx in ATTR_CHECKS.items() if not rx.search(text)]
    if missing_attrs:
        issues.append(("high", "Missing attributes agents filter on: " + ", ".join(missing_attrs)))
    if f["n_specs"] < 6:
        issues.append(("high", f"Only {f['n_specs']} measurable specs. Agents compare numbers (size, capacity, runtime, decibels); vague claims can't be compared."))
    if f["intent_coverage"] < 0.45:
        all_q = Counter(stem(t) for q in intents for t in tokens(q))
        have = {stem(t) for t in tokens(text)}
        gaps = [w for w, _ in all_q.most_common(40) if w not in have][:10]
        issues.append(("high", "Shopper requests use words the listing never addresses: " + ", ".join(gaps)))
    if f["n_bullets"] < 5:
        issues.append(("med", f"{f['n_bullets']} bullet points. Use 5+ bullets, each one fact an agent can quote."))
    if f["desc_words"] < 40:
        issues.append(("med", "Description is missing or very short. Agents read it to resolve edge cases (who it is for, what it is not for)."))
    if f["fluff_per_100"] > 1.0:
        found = [w for w in FLUFF if w in text.lower()][:6]
        issues.append(("med", "Marketing language agents discount: " + ", ".join(f'"{w}"' for w in found)))
    if f["title_words"] > 30:
        issues.append(("low", "Title is very long; lead with brand + product type + the 2-3 specs that decide the purchase."))
    if not lst.get("price"):
        issues.append(("low", "No price in the feed. Agents with a budget skip products whose price they cannot read."))
    return {"score": score, "parts": {k: round(v, 1) for k, v in parts.items()}, "features": f, "issues": issues}


# --------------------------------------------------------------------------------------
# Proxy agent (no API key needed)
# --------------------------------------------------------------------------------------
def proxy_score(lst: dict, intent: str) -> float:
    q = [stem(t) for t in tokens(intent)]
    doc = [stem(t) for t in tokens(full_text(lst))]
    tf = Counter(doc)
    dl = len(doc) or 1
    # BM25-like relevance on the shopper request
    rel = sum((tf[t] * 2.2) / (tf[t] + 1.2 * (0.25 + 0.75 * dl / 120)) for t in set(q) if tf[t])
    rel /= max(1, len(set(q)))
    f = listing_features(lst, intent)
    numbers_in_intent = re.findall(r"\d+", intent)
    num_hit = sum(1 for n in numbers_in_intent if re.search(rf"\b{n}\b", full_text(lst))) / max(1, len(numbers_in_intent)) if numbers_in_intent else 0
    return (3.0 * rel + 2.0 * f["title_coverage"] + 0.08 * min(f["n_specs"], 15)
            + 1.0 * f["attr_coverage"] + 0.8 * num_hit - 0.25 * f["fluff_per_100"])


def proxy_simulate(shelf: List[dict], target_id: str, intents: List[str], runs_per_intent: int = 30, seed: int = 0) -> dict:
    rng = random.Random(seed)
    results = []
    for intent in intents:
        scores = {p["id"]: proxy_score(p, intent) for p in shelf}
        wins = Counter()
        for _ in range(runs_per_intent):  # noisy agent: different agents / phrasings
            noisy = {k: v + rng.gauss(0, 0.35) for k, v in scores.items()}
            wins[max(noisy, key=noisy.get)] += 1
        ranked = sorted(scores, key=scores.get, reverse=True)
        results.append({
            "intent": intent,
            "chosen": ranked[0],
            "target_rank": ranked.index(target_id) + 1,
            "target_win_rate": wins[target_id] / runs_per_intent,
            "shortlisted": target_id in ranked[:3],
            "reason_for_target": _proxy_reason(next(p for p in shelf if p["id"] == target_id), intent, ranked.index(target_id) + 1),
            "missing_info": [],
            "n_trials": runs_per_intent,
        })
    return _summarize(results, len(shelf))


def _proxy_reason(lst, intent, rank):
    f = listing_features(lst, intent)
    bits = []
    if f["query_coverage"] < 0.5:
        q = {stem(t) for t in tokens(intent)}
        have = {stem(t) for t in tokens(full_text(lst))}
        bits.append("does not mention: " + ", ".join(sorted(q - have)[:6]))
    if f["n_specs"] < 6:
        bits.append("few comparable specs")
    if f["fluff_per_100"] > 1:
        bits.append("claims without numbers")
    head = "Picked" if rank == 1 else f"Ranked #{rank}"
    return head + (" - " + "; ".join(bits) if bits else " - strong match on request terms and specs")


# --------------------------------------------------------------------------------------
# Claude agent
# --------------------------------------------------------------------------------------
class ProductVerdict(BaseModel):
    product_id: str
    decision: Literal["chosen", "shortlisted", "rejected"]
    reason: str = Field(description="One sentence: the deciding reason, citing listing facts")


class AgentDecision(BaseModel):
    chosen_product_id: str
    ranking: List[str] = Field(description="All product ids, best to worst for this shopper")
    verdicts: List[ProductVerdict]
    missing_info_that_would_change_decision: List[str] = Field(
        description="Facts that were absent from listings and that you would have needed")


AGENT_SYSTEM = """You are an autonomous AI shopping agent buying on behalf of a user.
You only see the product data feed (title, brand, bullet points, description, attributes, price).
You never see ads, images, or brand marketing pages. Choose the product that best satisfies the
user's stated needs and constraints. Prefer verifiable, specific facts over marketing claims.
If a listing does not state a fact the user requires, treat it as unknown (a risk), not as true.
Rank every product and give a one-sentence deciding reason for each."""


def _feed(shelf: List[dict], rng: random.Random) -> tuple[str, dict]:
    order = shelf[:]
    rng.shuffle(order)
    alias = {}
    blocks = []
    for i, p in enumerate(order, 1):
        pid = f"P{i}"
        alias[pid] = p["id"]
        attrs = "".join(f"\n  - {k}: {v}" for k, v in (p.get("attributes") or {}).items())
        blocks.append(
            f"[{pid}]\nTitle: {p['title']}\nBrand: {p.get('brand') or 'n/a'}\nPrice: {p.get('price') or 'not listed'}\n"
            "Bullets:\n" + "\n".join(f"  - {b}" for b in p.get("bullets", [])[:8])
            + f"\nDescription: {(p.get('description') or 'n/a')[:900]}"
            + (f"\nAttributes:{attrs}" if attrs else ""))
    return "\n\n".join(blocks), alias


def _client(api_key: Optional[str]):
    import anthropic
    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()


def llm_decide(client, model: str, shelf: List[dict], intent: str, seed: int) -> tuple[AgentDecision, dict]:
    feed, alias = _feed(shelf, random.Random(seed))
    resp = client.messages.parse(
        model=model,
        max_tokens=4000,
        system=AGENT_SYSTEM,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": f"User request: {intent}\n\nProducts available:\n\n{feed}"}],
        output_format=AgentDecision,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"Agent call did not return a decision (stop_reason={resp.stop_reason})")
    return resp.parsed_output, alias


def llm_simulate(shelf, target_id, intents, model, api_key=None, runs_per_intent=2) -> dict:
    client = _client(api_key)
    jobs = [(intent, s) for intent in intents for s in range(runs_per_intent)]

    def run(job):
        intent, s = job
        d, alias = llm_decide(client, model, shelf, intent, seed=zlib.crc32(intent.encode()) % 1000 + s)
        inv = {v: k for k, v in alias.items()}
        tgt_alias = inv[target_id]
        ranking = [alias.get(x, x) for x in d.ranking]
        rank = ranking.index(target_id) + 1 if target_id in ranking else len(shelf)
        reason = next((v.reason for v in d.verdicts if v.product_id == tgt_alias), "")
        return {"intent": intent, "chosen": alias.get(d.chosen_product_id, d.chosen_product_id),
                "target_rank": rank, "won": alias.get(d.chosen_product_id) == target_id,
                "reason_for_target": reason, "missing_info": d.missing_info_that_would_change_decision,
                "winner_reason": next((v.reason for v in d.verdicts if v.product_id == d.chosen_product_id), "")}

    def safe_run(job):
        try:
            return run(job)
        except Exception as ex:  # one failed call should not sink the whole simulation
            return {"intent": job[0], "error": str(ex)}

    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(safe_run, jobs))
    raw = [r for r in out if "error" not in r]
    errors = [r["error"] for r in out if "error" in r]
    if not raw:
        raise RuntimeError("All agent calls failed. First error: " + errors[0])

    results = []
    for intent in intents:
        rs = [r for r in raw if r["intent"] == intent]
        if not rs:
            continue
        results.append({
            "intent": intent,
            "chosen": Counter(r["chosen"] for r in rs).most_common(1)[0][0],
            "target_rank": sum(r["target_rank"] for r in rs) / len(rs),
            "target_win_rate": sum(r["won"] for r in rs) / len(rs),
            "shortlisted": any(r["target_rank"] <= 3 for r in rs),
            "reason_for_target": rs[0]["reason_for_target"],
            "winner_reason": rs[0]["winner_reason"],
            "missing_info": sorted({m for r in rs for m in r["missing_info"]})[:6],
            "n_trials": len(rs),
        })
    res = _summarize(results, len(shelf))
    res["failed_calls"] = len(errors)
    return res


def wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion p observed over n trials."""
    if n <= 0:
        return (0.0, 1.0)
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _summarize(results, n_shelf):
    win = sum(r["target_win_rate"] for r in results) / len(results)
    n = sum(r.get("n_trials", 1) for r in results)
    short = sum(r["shortlisted"] for r in results) / len(results)
    rank = sum(r["target_rank"] for r in results) / len(results)
    return {"win_rate": win, "win_ci": wilson(win, n), "n_trials": n, "shortlist_rate": short,
            "avg_rank": rank, "fair_share": 1 / n_shelf, "per_intent": results}


# --------------------------------------------------------------------------------------
# Rewrite
# --------------------------------------------------------------------------------------
class Attribute(BaseModel):
    name: str
    value: str


class Change(BaseModel):
    change: str
    why_agents_care: str


class Rewrite(BaseModel):
    title: str
    bullets: List[str]
    description: str
    attributes: List[Attribute]
    changes: List[Change]
    seller_must_confirm: List[str] = Field(
        description="Facts shoppers ask about that the original listing did not state; the seller must supply them")


REWRITE_SYSTEM = """You optimize Amazon product listings for AI shopping agents (not humans skimming).
Rules:
- Never invent facts. Use only facts in the original listing. You may restate, restructure, quantify
  what is already implied, and remove fluff.
- Put brand, product type, and the 2-3 deciding specs in the title (max ~150 characters).
- 5-7 bullets; each bullet starts with a short label then one checkable fact (e.g. "Coverage: up to 300 sq ft").
- Add a structured attribute list (name/value) of every concrete fact you can find.
- Address the words and needs real shoppers use (given below) when the listing supports them.
- Anything shoppers need that the listing does not state goes in seller_must_confirm, not in the copy."""


def llm_rewrite(lst: dict, market: dict, audit_res: dict, sim_res: Optional[dict], model: str, api_key=None) -> dict:
    client = _client(api_key)
    feedback = ""
    if sim_res:
        feedback = "\n".join(f"- Shopper: {r['intent']}\n  Agent on this product: {r['reason_for_target']}\n  Missing: {', '.join(r.get('missing_info') or [])}"
                             for r in sim_res["per_intent"])
    issues = "\n".join(f"- {t}" for _, t in audit_res["issues"])
    orig = (f"Title: {lst['title']}\nBrand: {lst.get('brand')}\nPrice: {lst.get('price') or 'n/a'}\nBullets:\n"
            + "\n".join(f"- {b}" for b in lst.get("bullets", [])) + f"\nDescription: {lst.get('description')}")
    prompt = (f"Category search: {market['query']}\nReal shopper requests:\n" + "\n".join(f"- {i}" for i in market["intents"])
              + f"\n\nAudit issues:\n{issues}\n\nWhat simulated shopping agents said:\n{feedback or 'n/a'}\n\nORIGINAL LISTING\n{orig}")
    resp = client.messages.parse(model=model, max_tokens=8000, system=REWRITE_SYSTEM,
                                 output_config={"effort": "medium"},
                                 messages=[{"role": "user", "content": prompt}], output_format=Rewrite)
    if resp.parsed_output is None:
        raise RuntimeError(f"Rewrite failed (stop_reason={resp.stop_reason})")
    r = resp.parsed_output
    return {"title": r.title, "brand": lst.get("brand", ""), "price": lst.get("price", ""), "bullets": r.bullets,
            "description": r.description, "attributes": {a.name: a.value for a in r.attributes},
            "changes": [c.model_dump() for c in r.changes], "seller_must_confirm": r.seller_must_confirm}


def proxy_rewrite(lst: dict, market: dict) -> dict:
    """Rule-based restructure: no new facts, remove fluff, surface specs, lead with product type."""
    text = full_text(lst)
    def defluff(s):
        for f in FLUFF:
            s = re.sub(rf"(?i)\b{re.escape(f)}\b", "", s)
        return re.sub(r"\s{2,}", " ", s).strip(" ,-")
    specs = list(dict.fromkeys(m.group(0).strip() for m in UNIT_RE.finditer(text)))
    qtype = market["query"].replace("best ", "").title()
    brand = lst.get("brand") or ""
    title_core = defluff(lst["title"])
    if qtype.lower().split()[-1] not in title_core.lower():
        title_core = f"{title_core} - {qtype}"
    title = (f"{brand} " if brand and brand.lower() not in title_core.lower() else "") + title_core
    if len(title) > 110:  # cut at a word/comma boundary
        title = title[:110].rsplit(",", 1)[0] if "," in title[:110] else title[:110].rsplit(" ", 1)[0]
    deciding = [s for s in specs if not re.search(r"%|hours?|hrs?|mins?|minutes?|days?|months?", s, re.I)
                and s.lower() not in title.lower()]
    if deciding:
        title = title + " | " + ", ".join(deciding[:3])
    bullets = []
    for b in lst.get("bullets", []):
        b = defluff(b)
        if not b:
            continue
        label = " ".join(tokens(b)[:3]).title() or "Detail"
        bullets.append(b if ":" in b[:40] else f"{label}: {b}")
    attrs = {}
    for k, rx in ATTR_CHECKS.items():
        m = rx.search(text)
        if m:
            i = m.start()
            attrs[ATTR_LABELS[k]] = text[max(0, i - 40): i + 80].replace("\n", " ").strip()
    if specs:
        attrs["Key specs"] = ", ".join(specs[:10])
    missing = [ATTR_LABELS[k] for k, rx in ATTR_CHECKS.items() if not rx.search(text)]
    return {"title": title, "brand": brand, "price": lst.get("price", ""), "bullets": bullets[:7],
            "description": defluff(lst.get("description") or ""), "attributes": attrs,
            "changes": [{"change": "Removed marketing superlatives", "why_agents_care": "Agents discount unverifiable claims."},
                        {"change": "Moved specs into title and an attribute list", "why_agents_care": "Agents filter and compare on structured numbers."},
                        {"change": "Labeled each bullet", "why_agents_care": "Labeled facts are easier for a model to extract and quote."}],
            "seller_must_confirm": missing}
