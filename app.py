"""AgentShelf - get your Amazon listing picked when the shopper is an AI agent.

Run:  .venv/bin/streamlit run app.py
"""
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

import engine as E

st.set_page_config(page_title="AgentShelf", page_icon="🛒", layout="wide")
DATA = Path(__file__).parent / "data"
MARKETS = json.loads((DATA / "markets.json").read_text())
INSIGHTS = json.loads((DATA / "insights.json").read_text())
N_COMPETITORS = 7

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Settings")
    key = st.text_input("Anthropic API key", value=os.environ.get("ANTHROPIC_API_KEY", ""), type="password",
                        help="Leave empty to use the built-in proxy agent.")
    mode = st.radio("Shopping agent", ["Claude agent", "Proxy agent (offline)"], index=0 if key else 1,
                    help="Claude agent: Claude reads the product feed and buys. Proxy agent: transparent scoring model, no key needed.")
    model = st.selectbox("Claude model", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"])
    runs = st.slider("Runs per shopper request", 1, 4, 2, help="Shelf order is reshuffled each run to remove position bias.")
    st.divider()
    mkey = st.selectbox("Product category", list(MARKETS), format_func=lambda k: MARKETS[k]["label"])
    st.caption("Listings are real Amazon US products from the Amazon Shopping Queries (ESCI) dataset.")

use_llm = mode.startswith("Claude")
if use_llm and not key:
    st.sidebar.warning("No API key: switch to the proxy agent or paste a key.")

market = MARKETS[mkey]
products = market["products"]

# ------------------------------------------------------------------ state
ss = st.session_state
if ss.get("mkey") != mkey:
    ss.clear()
    ss.mkey = mkey
    # default "your product": the weakest listing in the category (a typical small seller)
    exact = [p for p in products if p.get("esci_label") == "Exact"] or products
    scored = sorted(exact, key=lambda p: E.audit(p, market)["score"])
    ss.target_id = scored[len(scored) // 4]["id"]

st.title("🛒 AgentShelf")
st.markdown("**When the customer is a bot**, your listing is the whole sales pitch. "
            "AgentShelf tests how AI shopping agents rank your Amazon listing against real competitors, "
            "tells you why they pass on it, and rewrites it so they pick it.")

tab_run, tab_evidence, tab_about = st.tabs(["Optimize a listing", "Market evidence (ESCI data)", "How it works"])

# ================================================================== main tab
with tab_run:
    # ---------- 1. listing
    st.subheader("1 · Your listing")
    ids = [p["id"] for p in products]
    pick = st.selectbox("Start from a real listing in this category (or edit it below to paste your own)", ids,
                        index=ids.index(ss.target_id),
                        format_func=lambda i: next(p["title"][:110] for p in products if p["id"] == i))
    if pick != ss.target_id:
        ss.target_id = pick
        for k in ("sim_before", "sim_after", "rewrite", "sim_final", "final_listing"):
            ss.pop(k, None)
    base = next(p for p in products if p["id"] == ss.target_id)

    c1, c2 = st.columns([3, 1])
    title = c1.text_input("Title", base["title"], key=f"t_{base['id']}")
    brand = c2.text_input("Brand", base.get("brand", ""), key=f"b_{base['id']}")
    price = c2.text_input("Price (optional)", "", key=f"p_{base['id']}")
    bullets = c1.text_area("Bullet points (one per line)", "\n".join(base["bullets"]), height=180, key=f"bl_{base['id']}")
    desc = st.text_area("Description", base.get("description", ""), height=90, key=f"d_{base['id']}")
    mine = {"id": "YOU", "title": title, "brand": brand, "price": price,
            "bullets": [b for b in bullets.split("\n") if b.strip()], "description": desc}

    competitors = [p for p in products if p["id"] != base["id"]][:N_COMPETITORS]
    with st.expander(f"Competing listings on the shelf ({len(competitors)})"):
        for p in competitors:
            st.markdown(f"- **{p.get('brand') or '—'}** · {p['title'][:140]}")

    # ---------- 2. audit
    st.subheader("2 · Agent-readiness audit")
    a = E.audit(mine, market)
    comp_scores = [E.audit(p, market)["score"] for p in competitors]
    m1, m2, m3 = st.columns(3)
    m1.metric("Your agent-readiness", f"{a['score']}/100")
    m2.metric("Shelf average", f"{sum(comp_scores)/len(comp_scores):.0f}/100")
    m3.metric("Best competitor", f"{max(comp_scores)}/100")
    cA, cB = st.columns([1, 1.4])
    max_parts = {"Matches what shoppers ask for": 25, "Measurable specs": 20, "Key attributes stated": 20,
                 "Structure (title, 5 bullets, description)": 20, "Facts over fluff": 15}
    cA.dataframe(pd.DataFrame([{"Check": k, "Score": f"{v:.0f} / {max_parts[k]}"} for k, v in a["parts"].items()]),
                 hide_index=True, width="stretch")
    with cB:
        icon = {"high": "🔴", "med": "🟠", "low": "⚪"}
        for sev, txt in a["issues"]:
            st.markdown(f"{icon[sev]} {txt}")

    # ---------- 3. simulate
    st.subheader("3 · Send AI shoppers to the shelf")
    st.caption("Each shopper request below is given to a shopping agent that sees only the product feed "
               f"for your listing and {len(competitors)} competitors, in random order.")
    intents = st.text_area("Shopper requests (one per line)", "\n".join(market["intents"]), height=110, key=f"in_{mkey}")
    intents = [i.strip() for i in intents.split("\n") if i.strip()]
    shelf = [mine] + competitors

    def simulate(listing):
        sh = [listing] + competitors
        if use_llm:
            return E.llm_simulate(sh, "YOU", intents, model=model, api_key=key or None, runs_per_intent=runs)
        return E.proxy_simulate(sh, "YOU", intents)

    if st.button("Run agent shoppers", type="primary", disabled=use_llm and not key):
        with st.spinner(f"{len(intents) * (runs if use_llm else 30)} agent shopping trips..."):
            try:
                ss.sim_before = simulate(mine)
                ss.pop("sim_after", None)
                ss.pop("rewrite", None)
                ss.pop("sim_final", None)
            except Exception as ex:  # surface API problems in the UI
                st.error(f"Simulation failed: {ex}")

    title_of = {p["id"]: p["title"] for p in shelf}

    def show_sim(sim, label):
        k1, k2, k3, k4 = st.columns(4)
        lo, hi = sim["win_ci"]
        k1.metric(f"{label}: picked by agents", f"{sim['win_rate']:.0%}",
                  help=f"95% interval {lo:.0%}–{hi:.0%} over {sim['n_trials']} agent shopping trips")
        k2.metric("Fair share", f"{sim['fair_share']:.0%}")
        k3.metric("Made the top-3 shortlist", f"{sim['shortlist_rate']:.0%}")
        k4.metric("Average rank", f"{sim['avg_rank']:.1f} of {len(shelf)}")
        rows = []
        for r in sim["per_intent"]:
            rows.append({"Shopper request": r["intent"], "Your rank": round(r["target_rank"], 1),
                         "You won": f"{r['target_win_rate']:.0%}",
                         "Agent picked": "YOU" if r["chosen"] == "YOU" else title_of.get(r["chosen"], r["chosen"])[:60],
                         "What the agent said about you": r["reason_for_target"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(f"Based on {sim['n_trials']} agent shopping trips · 95% interval for pick rate: {lo:.0%}–{hi:.0%}"
                   + (f" · {sim['failed_calls']} calls failed and were skipped" if sim.get("failed_calls") else ""))
        miss = sorted({m for r in sim["per_intent"] for m in r.get("missing_info", [])})
        if miss:
            st.markdown("**Information agents wanted but could not find:** " + "; ".join(miss[:12]))

    if "sim_before" in ss:
        show_sim(ss.sim_before, "Current listing")

        # ---------- 4. rewrite
        st.subheader("4 · Rewrite for agents and re-test")
        if st.button("Generate agent-optimized listing", type="primary"):
            with st.spinner("Rewriting from audit + agent feedback..."):
                try:
                    if use_llm:
                        ss.rewrite = E.llm_rewrite(mine, market, a, ss.sim_before, model=model, api_key=key or None)
                    else:
                        ss.rewrite = E.proxy_rewrite(mine, market)
                    ss.rewrite["id"] = "YOU"
                    ss.sim_after = simulate(ss.rewrite)
                    ss.pop("sim_final", None)
                except Exception as ex:
                    st.error(f"Rewrite failed: {ex}")

    if "rewrite" in ss and "sim_after" in ss:
        rw, before, after = ss.rewrite, ss.sim_before, ss.sim_after
        a2 = E.audit(rw, market)
        st.success(f"Agent pick rate {before['win_rate']:.0%} → **{after['win_rate']:.0%}**   ·   "
                   f"Shortlist {before['shortlist_rate']:.0%} → **{after['shortlist_rate']:.0%}**   ·   "
                   f"Avg rank {before['avg_rank']:.1f} → **{after['avg_rank']:.1f}**   ·   "
                   f"Readiness {a['score']} → **{a2['score']}**")
        L, R = st.columns(2)
        with L:
            st.markdown("**Before**")
            st.markdown(f"**{mine['title']}**")
            for b in mine["bullets"]:
                st.markdown(f"- {b}")
        with R:
            st.markdown("**After (agent-optimized)**")
            st.markdown(f"**{rw['title']}**")
            for b in rw["bullets"]:
                st.markdown(f"- {b}")
            if rw.get("attributes"):
                st.markdown("*Structured attributes*")
                st.dataframe(pd.DataFrame([{"Attribute": k, "Value": v} for k, v in rw["attributes"].items()]),
                             hide_index=True, width="stretch")
            if rw.get("description"):
                with st.expander("Description"):
                    st.write(rw["description"])
        cX, cY = st.columns(2)
        with cX:
            st.markdown("**What changed and why agents care**")
            for c in rw.get("changes", []):
                st.markdown(f"- **{c['change']}** — {c['why_agents_care']}")
        with cY:
            if rw.get("seller_must_confirm"):
                st.markdown("**Seller to-do: facts shoppers ask for that your listing doesn't state**")
                for s in rw["seller_must_confirm"]:
                    st.markdown(f"- ☐ {s}")
        # ---------- 5. seller fills the gaps agents asked about
        if rw.get("seller_must_confirm"):
            st.subheader("5 · Fill the gaps agents asked about, then re-test")
            st.caption("Only you know these facts. Anything you enter is added to the listing as structured attributes.")
            answers = {}
            cols = st.columns(2)
            for i, item in enumerate(rw["seller_must_confirm"][:10]):
                answers[item] = cols[i % 2].text_input(item, key=f"ans_{i}")
            if st.button("Re-test with my answers", type="primary"):
                filled = {k: v for k, v in answers.items() if v.strip()}
                rw2 = dict(rw, attributes={**rw.get("attributes", {}), **filled})
                rw2["bullets"] = rw["bullets"] + [f"{k}: {v}" for k, v in filled.items()][:3]
                with st.spinner("Re-running agent shoppers..."):
                    try:
                        ss.sim_final = simulate(rw2)
                        ss.final_listing = rw2
                    except Exception as ex:
                        st.error(f"Simulation failed: {ex}")
            if "sim_final" in ss:
                f = ss.sim_final
                st.success(f"With your facts: agent pick rate {before['win_rate']:.0%} → {after['win_rate']:.0%} → "
                           f"**{f['win_rate']:.0%}**  ·  avg rank {before['avg_rank']:.1f} → {after['avg_rank']:.1f} → **{f['avg_rank']:.1f}**")
        with st.expander("Agent results for the rewritten listing"):
            show_sim(after, "Rewritten listing")
        st.download_button("Download rewritten listing (JSON)", json.dumps(rw, indent=2), file_name="agent_optimized_listing.json")

# ================================================================== evidence tab
with tab_evidence:
    st.subheader("What Amazon's own relevance labels say about listings")
    st.markdown(f"We scored **{INSIGHTS['n_pairs']:,}** real US query–product pairs from the Amazon Shopping Queries "
                "dataset, where Amazon labels each product as an *Exact* match, substitute, complement or irrelevant "
                f"for the search. Base rate of Exact: **{INSIGHTS['base_exact_rate']:.0%}**.")
    cov = pd.DataFrame(INSIGHTS["coverage_bins"])
    st.markdown("**Exact-match rate by how many of the shopper's words the title + bullets cover**")
    st.bar_chart(cov.set_index("bin")["exact_rate"], y_label="Exact-match rate", x_label="Query words covered", height=280)
    if True:
        lt = pd.DataFrame(INSIGHTS["lifts"])[["label", "exact_rate_low", "exact_rate_high", "coef"]]
        lt.columns = ["Listing feature", "Exact rate (low)", "Exact rate (high)", "Std. coefficient"]
        st.markdown("**Each feature, low vs high (median split) and logistic-regression weight**")
        st.dataframe(lt, hide_index=True, width="stretch")
    st.info("Takeaway: covering the shopper's own words is by far the strongest signal for being judged relevant "
            "(37% → 84% Exact). Specs, attributes and fluff barely move *relevance* — but relevance only gets you "
            "onto the shelf. Whether an agent *chooses* you is a different question that no public dataset labels, "
            "which is why AgentShelf simulates the choice with agent shoppers.")

    vpath = DATA / "validation.json"
    if vpath.exists():
        V = json.loads(vpath.read_text())
        st.subheader("Does the simulated agent behave like a sensible shopper?")
        st.markdown(f"Sanity check on **{V['n_queries']}** real queries, using Amazon's labels as ground truth "
                    "(an agent given the query should prefer products Amazon judged an *Exact* match).")
        v1, v2, v3 = st.columns(3)
        v1.metric("Proxy agent: picks the Exact product from 5", f"{V['proxy_pick_accuracy_1_of_5']:.0%}",
                  help=f"Random guessing: {V['random_pick_baseline']:.0%}")
        v2.metric("Ranks Exact above Irrelevant", f"{V['proxy_pairwise_exact_vs_irrelevant']:.0%}", help="50% = coin flip")
        v3.metric("Ranks Exact above Substitute", f"{V['proxy_pairwise_exact_vs_substitute']:.0%}", help="50% = coin flip")
        if "llm_pick_accuracy_1_of_5" in V:
            w1, w2 = st.columns(2)
            w1.metric(f"Claude agent ({V['llm_model']}): picks the Exact product", f"{V['llm_pick_accuracy_1_of_5']:.0%}")
            w2.metric("Claude agent: same pick after reshuffling the shelf", f"{V['llm_same_pick_after_reshuffle']:.0%}")
        else:
            st.caption("Claude-agent validation not run yet: `python validate.py --llm 30` with an API key.")

with tab_about:
    st.markdown("""
**User:** a small Amazon seller (1–20 products) who can't afford an agency and is losing sales they can't even see,
because AI assistants (Google's agent shopping standard, Copilot checkout, Rufus) choose the product before a human looks.

**Pipeline**
1. **Audit** – deterministic agent-readiness score: does the listing use shoppers' words, state measurable specs,
   cover the attributes agents filter on, avoid fluff? Weights informed by the ESCI analysis.
2. **Simulate** – a shelf of your listing + real competitors from the same Amazon search. Each realistic shopper request
   is sent to a shopping agent (Claude, structured output) that sees only the product feed, in shuffled order, and must rank
   every product with a reason. We report pick rate vs fair share, shortlist rate, rank, and the info agents missed.
3. **Rewrite** – Claude rewrites using only facts already in the listing, adds structured attributes, and lists what the
   seller must confirm (never invents specs). Then we **re-run the same agents** — an A/B test where the customer is a bot.

**Proxy mode** runs without an API key: a transparent BM25 + spec scoring agent with noise, so the demo always runs.

**Limits:** simulated agents are not the real Google/Amazon/Microsoft agents; results show direction, not exact share.
Rewrites must be checked by the seller before publishing.
""")
