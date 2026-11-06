"""Check that the simulated shopping agents behave sensibly, using Amazon's own labels as ground truth.

For real US queries in the ESCI dataset we know which products Amazon judged an Exact match and which
it judged Irrelevant or a Substitute. A credible shopping agent given the query should prefer Exact
products. We measure:

  1. Pairwise accuracy (proxy agent): P(score(Exact) > score(Irrelevant)) and vs Substitute.
  2. Pick accuracy (proxy agent): on a shelf of 1 Exact + 4 non-Exact products, how often it picks
     the Exact one. Random guessing = 20%.
  3. Optional, with --llm N: the same pick test for the Claude agent on N queries, plus a
     position-bias check (same shelf, reshuffled: does the agent pick the same product?).

Run:  .venv/bin/python validate.py              # proxy agent only, free
      .venv/bin/python validate.py --llm 30     # also test the Claude agent (about 60 API calls)
"""
import argparse
import json
import random
from pathlib import Path

import pandas as pd

import engine as E
from build_data import RAW, to_listing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=400)
    ap.add_argument("--llm", type=int, default=0, help="number of queries to test with the Claude agent")
    ap.add_argument("--model", default="claude-opus-5-5")
    args = ap.parse_args()

    rng = random.Random(11)
    df = pd.read_parquet(RAW)
    df = df[df.product_locale == "us"]
    groups = []
    for q, g in df.groupby("query"):
        ex = g[g.esci_label == "Exact"]
        irr = g[g.esci_label == "Irrelevant"]
        sub = g[g.esci_label == "Substitute"]
        if len(ex) >= 1 and len(irr) + len(sub) >= 4 and len(irr) >= 1:
            groups.append((q, ex, irr, sub))
    rng.shuffle(groups)
    groups = groups[: args.queries]

    pair_irr = pair_sub = n_irr = n_sub = 0
    pick_hits = 0
    shelves = []
    for q, ex, irr, sub in groups:
        e = [to_listing(r) for r in ex.itertuples()]
        i = [to_listing(r) for r in irr.itertuples()]
        s = [to_listing(r) for r in sub.itertuples()]
        se = [E.proxy_score(x, q) for x in e]
        for x in i:
            si = E.proxy_score(x, q)
            pair_irr += sum(a > si for a in se) + 0.5 * sum(a == si for a in se)
            n_irr += len(se)
        for x in s:
            ss = E.proxy_score(x, q)
            pair_sub += sum(a > ss for a in se) + 0.5 * sum(a == ss for a in se)
            n_sub += len(se)
        # pick test: 1 Exact + 4 others (Irrelevant first, then Substitute)
        target = rng.choice(e)
        others = (rng.sample(i, min(len(i), 4)) + rng.sample(s, len(s)))[:4]
        shelf = [target] + others
        pick = max(shelf, key=lambda x: E.proxy_score(x, q))
        pick_hits += pick["id"] == target["id"]
        shelves.append((q, target, shelf))

    out = {
        "n_queries": len(groups),
        "proxy_pairwise_exact_vs_irrelevant": round(pair_irr / max(1, n_irr), 3),
        "proxy_pairwise_exact_vs_substitute": round(pair_sub / max(1, n_sub), 3),
        "proxy_pick_accuracy_1_of_5": round(pick_hits / len(groups), 3),
        "random_pick_baseline": 0.2,
    }
    print(json.dumps(out, indent=2))

    if args.llm:
        client = E._client(None)
        hits = same = 0
        tested = shelves[: args.llm]
        for q, target, shelf in tested:
            shelf = [dict(p) for p in shelf]
            d1, a1 = E.llm_decide(client, args.model, shelf, q, seed=1)
            d2, a2 = E.llm_decide(client, args.model, shelf, q, seed=2)
            p1, p2 = a1.get(d1.chosen_product_id), a2.get(d2.chosen_product_id)
            hits += p1 == target["id"]
            same += p1 == p2
        out.update({
            "llm_model": args.model,
            "llm_n_queries": len(tested),
            "llm_pick_accuracy_1_of_5": round(hits / len(tested), 3),
            "llm_same_pick_after_reshuffle": round(same / len(tested), 3),
        })
        print(json.dumps(out, indent=2))

    Path("data/validation.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
