"""Unit tests for the deterministic parts of the engine (no API key needed).
Run:  .venv/bin/python -m pytest -q
"""
import json
from pathlib import Path

import engine as E

DATA = Path(__file__).resolve().parents[1] / "data"
MARKETS = json.loads((DATA / "markets.json").read_text())
M = MARKETS["air purifier"]

WEAK = {"id": "W", "title": "Best Amazing Premium Purifier", "brand": "", "bullets": ["Perfect gift", "High quality"],
        "description": ""}
STRONG = {"id": "S", "title": "Acme HEPA Air Purifier for Bedroom, 300 sq ft, 24 dB Quiet",
          "brand": "Acme",
          "bullets": ["Coverage: up to 300 sq ft bedroom", "Filter: H13 true HEPA, removes pet allergens and smoke",
                      "Noise: 24 dB in sleep mode, quiet night mode", "Safety: ozone free, CARB certified",
                      "Warranty: 2 years", "In the box: purifier, 1 filter, manual"],
          "description": "Designed for bedrooms and nurseries up to 300 sq ft. Weight 7 lbs. Made of ABS plastic. "
                         "Replacement filters easy to buy. Filter change indicator light." * 2}


def test_features_ranges():
    f = E.listing_features(STRONG, "air purifier bedroom")
    assert 0 <= f["query_coverage"] <= 1 and 0 <= f["attr_coverage"] <= 1
    assert f["n_specs"] >= 4 and f["n_bullets"] == 6


def test_audit_prefers_specific_listing():
    assert E.audit(STRONG, M)["score"] > E.audit(WEAK, M)["score"] + 30
    assert any("fluff" in t.lower() or "marketing" in t.lower() for _, t in E.audit(WEAK, M)["issues"])


def test_audit_handles_empty_listing():
    a = E.audit({"id": "E", "title": "", "bullets": [], "description": ""}, M)
    assert 0 <= a["score"] <= 100


def test_proxy_agent_picks_better_listing():
    shelf = [WEAK, STRONG] + M["products"][:3]
    res = E.proxy_simulate(shelf, "S", M["intents"])
    weak = E.proxy_simulate(shelf, "W", M["intents"])
    assert res["win_rate"] > weak["win_rate"]
    lo, hi = res["win_ci"]
    assert 0 <= lo <= res["win_rate"] <= hi <= 1


def test_proxy_simulation_is_reproducible():
    shelf = [STRONG] + M["products"][:5]
    assert E.proxy_simulate(shelf, "S", M["intents"]) == E.proxy_simulate(shelf, "S", M["intents"])


def test_proxy_rewrite_adds_no_new_numbers():
    import re
    rw = E.proxy_rewrite(dict(M["products"][0], id="YOU"), M)
    orig = E.full_text(M["products"][0])
    for num in re.findall(r"\d+(?:\.\d+)?", " ".join([rw["title"]] + rw["bullets"])):
        assert num in orig, f"rewrite invented number {num}"


def test_wilson_interval():
    lo, hi = E.wilson(0.5, 100)
    assert 0.39 < lo < 0.41 and 0.59 < hi < 0.61
    assert E.wilson(0, 0) == (0.0, 1.0)


def test_markets_data_shape():
    for m in MARKETS.values():
        assert len(m["products"]) >= 8 and len(m["intents"]) >= 3


class _FakeResp:
    def __init__(self, parsed):
        self.parsed_output, self.stop_reason = parsed, "end_turn"


class _FakeClient:
    """Stands in for anthropic.Anthropic: the 'agent' always picks the first product it is shown."""
    class messages:
        @staticmethod
        def parse(**kw):
            fmt = kw["output_format"]
            if fmt is E.AgentDecision:
                import re
                ids = sorted(set(re.findall(r"\[(P\d+)\]", kw["messages"][0]["content"])), key=lambda x: int(x[1:]))
                return _FakeResp(E.AgentDecision(
                    chosen_product_id=ids[0], ranking=ids,
                    verdicts=[E.ProductVerdict(product_id=i, decision="rejected", reason="r") for i in ids],
                    missing_info_that_would_change_decision=["noise in dB"]))
            return _FakeResp(E.Rewrite(title="t", bullets=["a: 1"], description="d",
                                       attributes=[E.Attribute(name="Coverage", value="300 sq ft")],
                                       changes=[E.Change(change="c", why_agents_care="w")],
                                       seller_must_confirm=["Warranty"]))


def test_llm_pipeline_with_fake_client(monkeypatch):
    monkeypatch.setattr(E, "_client", lambda key: _FakeClient())
    shelf = [dict(M["products"][0], id="YOU")] + M["products"][1:8]
    sim = E.llm_simulate(shelf, "YOU", M["intents"][:2], model="x", runs_per_intent=3)
    assert 0 <= sim["win_rate"] <= 1 and sim["n_trials"] == 6 and sim["failed_calls"] == 0
    assert sim["per_intent"][0]["missing_info"] == ["noise in dB"]
    rw = E.llm_rewrite(shelf[0], M, E.audit(shelf[0], M), sim, model="x")
    assert rw["attributes"] == {"Coverage": "300 sq ft"} and rw["seller_must_confirm"] == ["Warranty"]
