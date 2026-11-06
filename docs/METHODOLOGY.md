# AgentShelf methodology

This document is for technical readers: how the data is used, what each score means exactly, how the agent simulation is designed, how we checked it, and where it can be wrong. Every number here can be reproduced with the scripts in this repository (see [§9](#9-reproducing-everything)).

**Contents**
1. [Problem framing](#1-problem-framing)
2. [Data](#2-data)
3. [Listing features](#3-listing-features)
4. [What drives relevance: ESCI analysis](#4-what-drives-relevance-esci-analysis)
5. [Agent-readiness audit](#5-agent-readiness-audit)
6. [Shopping-agent simulation](#6-shopping-agent-simulation)
7. [Rewrite](#7-rewrite)
8. [Validation](#8-validation)
9. [Reproducing everything](#9-reproducing-everything)
10. [Limitations and risks](#10-limitations-and-risks)
11. [FAQ for skeptics](#11-faq-for-skeptics)

---

## 1. Problem framing

When an AI agent does the shopping, the seller's outcome depends on two steps:

1. **Retrieval (getting onto the shelf):** the agent's search returns your product as relevant to the request.
2. **Choice (getting picked):** among the relevant products, the agent picks yours.

Public data can help with step 1: Amazon's ESCI dataset labels query–product relevance. **No public dataset labels step 2**, and real agents' choices are not observable to sellers. AgentShelf therefore:

- uses ESCI to learn what drives step 1 and to build realistic shelves of real competing products, and
- **measures step 2 by simulation**: a shopping agent repeatedly chooses from a shelf, and we estimate the probability that it picks the seller's product (the *agent pick rate*).

The seller's decision variable is the listing text. The outcome is the pick rate. The tool runs a controlled experiment: same shelf, same shopper requests, listing A vs listing B.

## 2. Data

| Source | Use | Size used |
|---|---|---|
| [Amazon Shopping Queries Dataset (ESCI)](https://github.com/amazon-science/esci-data) (Reddy et al., 2022, Apache-2.0), via the Hugging Face mirror `tasksource/esci`, test shard 0 | Real queries, real product listings (title, brand, bullets, description, color) and Amazon's relevance labels: **E**xact, **S**ubstitute, **C**omplement, **I**rrelevant | 163,123 rows; **124,212 US rows**; 40,000-pair random sample for the analysis |
| Hand-written shopper requests | 4 realistic natural-language requests per category, of the kind a person gives an assistant (constraints such as room size, noise, budget, compatibility) | 6 categories × 4 requests |

**Category shelves** (`data/markets.json`, built by `build_data.py`): six high-volume ESCI queries: *air purifier*, *best white noise machine for baby*, *baby carrier*, *bark collars for medium dogs*, *1tb ssd*, *backpack*. For each one we keep US products labeled Exact or Substitute, drop those with an empty title or no text, de-duplicate near-identical titles, shuffle with a fixed seed, and keep 15. In the app, one product is the seller's listing and the next 7 are the competitors (a shelf of 8).

**Default "seller" listing:** the 25th-percentile Exact product by audit score in the category. It is a realistic, imperfect listing rather than the worst one or junk.

**What the data does not contain:** price, star rating, review count, images. The prototype judges products on listing text only. Sellers can type a price into the app and it is passed to the agent.

**Descriptive facts from the 40k sample:** 54% of listings have **no description at all**, and 10% have fewer than 3 bullets.

## 3. Listing features

Defined in `engine.listing_features(listing, query)`. Text is lowercased, tokenized, stop words are removed, and a light suffix stemmer is applied.

| Feature | Definition |
|---|---|
| `query_coverage` | \|query terms ∩ (title + bullets + attributes) terms\| / \|query terms\| |
| `title_coverage` | same as above, but against the title only |
| `n_specs` | count of numbers with a unit (sq ft, dB, lbs, mAh, TB, MB/s, hours, inches, CADR, …), found by a regular expression |
| `n_bullets` | number of bullet points |
| `desc_words` | words in the description |
| `title_words` | words in the title |
| `fluff_per_100` | marketing terms ("best", "premium", "amazing", "#1", "perfect gift", …) per 100 words |
| `attr_coverage` | share of 7 attribute groups mentioned: size/capacity, weight, materials, compatibility/use, warranty/returns, certification/safety, what's included (one regular expression each) |

These are deliberately simple and interpretable, so a seller can see exactly why the score moved.

## 4. What drives relevance: ESCI analysis

`build_data.py` computes the features for a random 40,000-pair sample (seed 7) and fits a logistic regression on standardized features: target = `label == Exact` (base rate 60.6%).

**Exact-match rate by query coverage:**

| Shopper's words covered by title + bullets | Exact rate | n |
|---|---|---|
| 0–25% | 37.2% | 8,068 |
| 25–50% | 52.0% | 10,568 |
| 50–75% | 59.2% | 8,877 |
| 75–100% | **84.0%** | 12,487 |

**Each feature: Exact rate below vs above the median, and the standardized coefficient:**

| Feature | Exact rate (low) | Exact rate (high) | Std. coef. |
|---|---|---|---|
| query_coverage | 48.5% | 80.2% | **+0.50** |
| title_coverage | 48.4% | 76.0% | **+0.35** |
| title_words | 59.5% | 61.7% | −0.11 |
| attr_coverage | 59.6% | 62.1% | −0.07 |
| n_bullets | 54.2% | 61.1% | +0.03 |
| fluff_per_100 | 59.3% | 61.9% | −0.01 |
| desc_words | 59.2% | 62.3% | −0.00 |
| n_specs | 58.6% | 62.7% | −0.00 |

**How we read it:**
- Covering the shopper's vocabulary is by far the dominant signal for relevance. This is why "Matches what shoppers ask for" carries the most weight in the audit (25 of 100 points).
- Specs, attributes, structure and fluff barely move *relevance*. That doesn't mean they don't matter: ESCI's labels are about whether a product matches a query, not whether a buyer chooses it among matching products. Choice is where specifics should matter (an agent can't confirm "quiet enough to sleep" without a dB number), so we measure it by simulation (§6) instead of asserting it.
- These are associations, not causal effects. The two coverage features are correlated with each other, so their individual coefficients should not be over-read.

## 5. Agent-readiness audit

`engine.audit(listing, market)` returns a 0–100 score. Coverage is averaged over the category query **and** all shopper requests (`intent_coverage`), so it reflects what agents are actually asked.

| Component | Formula | Max |
|---|---|---|
| Matches what shoppers ask for | min(1, intent_coverage / 0.6) × 25 | 25 |
| Measurable specs | min(1, n_specs / 10) × 20 | 20 |
| Key attributes stated | attr_coverage × 20 | 20 |
| Structure | [0.5·min(1, n_bullets/5) + 0.3·min(1, desc_words/60) + (0.2 if 8 ≤ title_words ≤ 30, else 0.05)] × 20 | 20 |
| Facts over fluff | max(0, 1 − fluff_per_100 / 3) × 15 | 15 |

The weights are informed by §4 (coverage first) and by marketplace listing best practice for the rest. They are a **heuristic checklist, not a fitted model**, and the audit is a fast pre-check. The decision metric is the simulated pick rate in §6. Issues are generated from the same features with fixed thresholds (for example, fewer than 6 specs is flagged as high severity).

## 6. Shopping-agent simulation

### 6.1 Design (shared by both agents)

- **Shelf:** the seller's listing + 7 real competitors from the same ESCI query (8 products, fair share 12.5%).
- **Shopper requests:** the category's 4 requests, editable in the app.
- **Visibility:** the agent sees only feed fields: title, brand, price (or "not listed"), up to 8 bullets, description (truncated to 900 characters) and structured attributes. No images, ads or reviews, which mirrors how agentic-commerce feeds work.
- **Controlled comparison:** before and after a rewrite, everything except the seller's listing is held fixed: the same competitors, requests, model and seeds.
- **Metrics:** pick rate (mean over requests of the per-request win share), top-3 shortlist rate, average rank, and a **95% Wilson interval** for the pick rate over all shopping trips.

### 6.2 Claude agent (`engine.llm_simulate`)

- **Model:** selectable: `claude-opus-5-5` (default), `claude-sonnet-5-5`, `claude-haiku-5-5`, with `effort: low` to keep it fast.
- **System prompt (abridged):** *"You are an autonomous AI shopping agent buying on behalf of a user. You only see the product data feed … Prefer verifiable, specific facts over marketing claims. If a listing does not state a fact the user requires, treat it as unknown (a risk), not as true. Rank every product and give a one-sentence deciding reason for each."*
- **Anonymization and order:** products are relabeled P1…P8 and shuffled with a seed derived from the request text (CRC32) plus the run index, so the agent can't favor a position or recognize the seller's product.
- **Structured output:** responses are parsed into a Pydantic schema (`AgentDecision`): the chosen ID, a full ranking, a per-product verdict and reason, and `missing_info_that_would_change_decision`. This forces a complete ranking, makes the output machine-checkable, and produces the "what agents couldn't find" list.
- **Runs:** `runs_per_intent` (1–4) reshuffled runs per request, executed in parallel (8 threads). Failed calls are skipped and counted. If every call fails, the run errors out.
- **Cost:** with 4 requests × 2 runs, one simulation is 8 calls and a full before/after/after-gaps session is about 24 calls.

### 6.3 Proxy agent (`engine.proxy_simulate`): offline, transparent

A noisy utility model, so the app always runs and every decision can be explained:

```
utility(product, request) = 3.0 · BM25-like relevance(request terms, product text)
                          + 2.0 · title_coverage
                          + 0.08 · min(n_specs, 15)
                          + 1.0 · attr_coverage
                          + 0.8 · share of numbers in the request that appear in the listing
                          − 0.25 · fluff_per_100
pick = argmax(utility + ε),  ε ~ N(0, 0.35²),  30 draws per request, fixed seed
```

The Gaussian noise stands in for variation between agents and phrasings (a random-utility, logit-style choice model). Results are deterministic for a given input. The proxy agent can't read meaning: it rewards specific, on-topic, quantified text, which is the direction §4 and agent-commerce guidance point to. Use the Claude agent for semantic judgments.

## 7. Rewrite

**Claude rewrite (`engine.llm_rewrite`, `effort: medium`).** Inputs: the original listing, the category's shopper requests, the audit issues, and the agents' per-request comments and missing-info lists from the simulation. Hard rules in the system prompt:
- **Never invent facts.** Use only facts in the original. Restating, restructuring and removing fluff are allowed.
- The title leads with brand + product type + the 2–3 deciding specs (about 150 characters max).
- 5–7 bullets, each in the form "Label: one checkable fact."
- A structured attribute list of every concrete fact found.
- Anything shoppers need that the listing doesn't state goes to `seller_must_confirm`, not into the copy.

The output is validated against a Pydantic schema (`Rewrite`), which includes a `changes` list explaining why each change matters to agents.

**Proxy rewrite (`engine.proxy_rewrite`)** is rule-based: it strips fluff terms, adds the product type to the title if missing, appends up to 3 deciding specs taken from the text, labels bullets, extracts attribute snippets, and lists missing attribute groups. A unit test checks that it **never introduces a number that wasn't in the original**.

**Seller gap-filling.** The seller's answers to `seller_must_confirm` are added as attributes and up to 3 bullets, then the same simulation is re-run. This is the only step where new facts enter, and they come from the seller.

## 8. Validation

`validate.py` checks that the agents behave like sensible shoppers, using Amazon's labels as ground truth: given the raw query, a good agent should prefer products Amazon judged *Exact*. We sample 400 US queries that have at least 1 Exact and 1 Irrelevant product and at least 4 non-Exact products.

| Test | Proxy agent | Chance |
|---|---|---|
| Ranks an Exact product above an Irrelevant one (pairwise) | **65.2%** | 50% |
| Ranks an Exact product above a Substitute (pairwise) | **59.9%** | 50% |
| Picks the single Exact product from a shelf of 1 Exact + 4 non-Exact | **40.5%** | 20% |

**How we read it:** the offline proxy agent is clearly better than chance (about 2× on the pick test), but far from perfect. Substitutes are often legitimately close, and short ESCI queries give it little to work with. That is acceptable for its role (an always-available demo and an explainable baseline) and is why the Claude agent is the primary simulator.

**Claude agent validation:** `python validate.py --llm 30` runs the same pick test with the Claude agent and adds a **position-bias check** (the same shelf in two different orders: how often is the same product chosen?). The results are written to `data/validation.json` and shown in the app's evidence tab. *We have not yet run this with a live key. Run it before the final presentation and quote the result.*

**Software tests:** `tests/test_engine.py` (9 tests, no key needed) covers feature ranges, audit ordering (a specific listing beats a fluffy one by more than 30 points), empty-listing safety, the proxy agent preferring the better listing, reproducibility, the no-new-numbers rule for the rewrite, the Wilson interval, the data shape, and the full Claude pipeline end to end with a fake client (ID de-anonymization, aggregation, rewrite parsing).

## 9. Reproducing everything

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# raw data (160 MB, not committed)
mkdir -p data/raw
curl -L -o data/raw/esci_test0.parquet \
  "https://huggingface.co/datasets/tasksource/esci/resolve/main/data/test-00000-of-00004-d48474212b95f33b.parquet"

.venv/bin/python build_data.py          # -> data/markets.json, data/insights.json (≈30 s)
.venv/bin/python validate.py            # -> data/validation.json (proxy agent, ≈20 s)
ANTHROPIC_API_KEY=... .venv/bin/python validate.py --llm 30   # optional, about 60 API calls
.venv/bin/python -m pytest -q           # unit tests
.venv/bin/streamlit run app.py
```

All sampling uses fixed seeds: 7 for the analysis sample, 42 for the shelves, 11 for validation, and 0 plus the request CRC32 for the simulations.

## 10. Limitations and risks

| Risk | Why it matters | Mitigation in the prototype / next step |
|---|---|---|
| **Simulated ≠ real agents** | Google, Amazon (Rufus) and Copilot agents use their own models, retrieval and signals (price, reviews, delivery) | We report direction and relative lift, not market share. Next: calibrate against real outcomes (a seller's agent-referred sales) and run several model families as a "panel" |
| **Same model writes and judges** | A Claude rewrite judged by a Claude agent could overfit to Claude's taste | Switch the judge model in the sidebar. The proxy agent is an independent check. Next: a cross-model panel |
| **Position / order bias** | LLMs can favor the first or last option | Anonymized IDs, reshuffled order on every run, and the position-bias check in `validate.py` |
| **Small samples** | 8 calls give a wide interval | Wilson 95% interval shown in the UI. Raise runs per request for decisions |
| **Hallucinated specs in rewrites** | False claims are a policy and legal risk for the seller | A "never invent" rule, a `seller_must_confirm` list instead of guesses, a unit test for the proxy rewrite, and a mandatory human review before publishing |
| **Gaming / keyword stuffing** | Over-optimizing for one agent could hurt human readers or break marketplace rules | The rewrite only restructures true facts. The fluff penalty discourages stuffing. Agents are told to prefer verifiable facts |
| **No price, reviews or images in the data** | Real agents weigh these heavily | Optional price field. Next: Amazon Reviews 2023 metadata (price, rating) for richer shelves |
| **Fixed shelves** | Competitors change daily | Next: pull live competitors for the seller's actual search terms |

## 11. FAQ for skeptics

**Why not just train a model on ESCI and optimize the listing against it?**
ESCI labels relevance (step 1), not choice (step 2). Optimizing against relevance labels would mostly teach "repeat the query words", which §4 already captures and the audit already rewards. The interesting question, which relevant product an agent picks, has no labels, so we simulate it.

**Isn't an LLM judging LLM-written text circular?**
Partly, yes, which is why the design holds everything fixed except the listing, lets you switch the judge model, includes an independent non-LLM agent, and forbids the rewrite from adding facts. Most of the measured gains come from making *existing* facts explicit and from the seller adding true missing facts. A different model should reward those changes too.

**How do you know the agent isn't just picking the first product?**
Products are anonymized and reshuffled on every run, and `validate.py --llm` measures how often the pick stays the same after a reshuffle.

**Is the audit score validated?**
The audit is a transparent heuristic that guides the seller. The pick rate is the outcome metric. Only the coverage weighting is directly supported by the ESCI regression, and we say so.

**Why trust a 16% → 51% jump?**
In the example it comes from the proxy agent with 120 trips per listing. Read it as "this change moved the listing from below fair share to the top of the shelf for these requests", together with its interval. With the Claude agent, use 3–4 runs per request for decisions.

**What would make this production-grade?**
Live competitor shelves for the seller's real search terms, a panel of several agent models, calibration against real agent-referred sales, price and review signals, and weekly monitoring of pick rate as competitors change.
