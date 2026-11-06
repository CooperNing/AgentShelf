"""Build the demo data from the Amazon Shopping Queries (ESCI) dataset.

Outputs
  data/markets.json   - a few product "shelves" (one per shopper need) with real Amazon listings
  data/insights.json  - what listing features go with Amazon's own "Exact match" relevance label,
                        computed over ~124k real US query/product pairs

Run:  .venv/bin/python build_data.py
"""
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from engine import listing_features, FEATURE_LABELS

RAW = Path("data/raw/esci_test0.parquet")
OUT = Path("data")

# Shopper needs we demo. Each has realistic requests a person would give an AI assistant.
MARKETS = {
    "air purifier": {
        "label": "Air purifier",
        "intents": [
            "I need an air purifier for my 300 sq ft bedroom. I have pet allergies, so it must have a true HEPA filter, and it has to be quiet enough to sleep with.",
            "Find me a small air purifier for a home office that runs quietly and has replacement filters that are easy to buy. Budget is around $100.",
            "My apartment gets wildfire smoke. Get me an air purifier that removes smoke and odor, with a CADR rating for a living room about 400 sq ft.",
            "Buy an air purifier for a nursery. No ozone, quiet night mode, and a filter-change indicator.",
        ],
    },
    "best white noise machine for baby": {
        "label": "White noise machine (baby)",
        "intents": [
            "Get me a white noise machine for my newborn's room. It should run all night without a timer cutting off and not have loud fan clicks.",
            "I want a portable sound machine for a baby that we can take when traveling, rechargeable, with a few sound options.",
            "Find a baby sound machine with a night light and volume that goes low enough to be safe for an infant.",
            "Buy a white noise machine for a toddler. Something simple, plug-in, with at least 10 sounds and a timer option.",
        ],
    },
    "baby carrier": {
        "label": "Baby carrier",
        "intents": [
            "I need a baby carrier for a newborn, ergonomic hip-healthy position, that also works when the baby is older, up to about 30 lbs.",
            "Find a lightweight breathable baby carrier for hot weather that my husband and I can both adjust.",
            "Buy a baby carrier with lumbar support because I have back pain. Front and back carrying positions please.",
            "Get a soft wrap-style carrier for a newborn, machine washable.",
        ],
    },
    "bark collars for medium dogs": {
        "label": "Bark collar (medium dogs)",
        "intents": [
            "My 40 lb dog barks at everything. Find a humane bark collar, ideally beep and vibration only, no shock.",
            "Get me a rechargeable bark collar for a medium dog that is waterproof and has adjustable sensitivity.",
            "I want a bark collar for a 25-50 lb dog with automatic mode and safety features so it won't over-correct.",
            "Buy a bark collar that fits a neck size around 14-18 inches and has a long battery life.",
        ],
    },
    "1tb ssd": {
        "label": "1TB SSD",
        "intents": [
            "Upgrade my laptop storage: I need a 1TB internal SSD that is M.2 NVMe and fast, at least 3000 MB/s read.",
            "Find a 1TB SSD for an older desktop with SATA ports. Reliable brand, 5 year warranty if possible.",
            "I need a portable 1TB SSD for video editing on a Mac, USB-C, rugged.",
            "Buy a 1TB SSD for a PS5 storage expansion. It needs to meet the PS5 speed requirements and have a heatsink.",
        ],
    },
    "backpack": {
        "label": "Backpack",
        "intents": [
            "Find me a backpack for work that fits a 15.6 inch laptop, has a USB charging port, and is water resistant.",
            "I need a lightweight travel backpack that fits airline carry-on size limits.",
            "Get a durable school backpack for a high schooler with lots of compartments and padded straps.",
            "Buy a backpack for day hiking, around 20-30 liters, with a water bottle pocket.",
        ],
    },
}

COMP_PER_MARKET = 9  # products on each shelf besides the seller's


def clean(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return str(v).strip()


def to_listing(r):
    bullets = [b.strip() for b in clean(r.product_bullet_point).split("\n") if b.strip()]
    return {
        "id": r.product_id,
        "title": clean(r.product_title),
        "brand": clean(r.product_brand),
        "color": clean(r.product_color),
        "bullets": bullets,
        "description": clean(r.product_description),
        "esci_label": r.esci_label,
    }


def main():
    df = pd.read_parquet(RAW)
    df = df[df.product_locale == "us"].copy()
    print("US rows:", len(df))

    # ---------------- insights: which listing features go with "Exact" -----------------
    sample = df.sample(n=min(40000, len(df)), random_state=7)
    feats = []
    for r in sample.itertuples():
        lst = to_listing(r)
        f = listing_features(lst, r.query)
        feats.append(f)
    F = pd.DataFrame(feats)
    y = (sample.esci_label.values == "Exact").astype(int)
    cols = list(FEATURE_LABELS.keys())
    X = StandardScaler().fit_transform(F[cols].values)
    model = LogisticRegression(max_iter=1000).fit(X, y)
    coefs = dict(zip(cols, model.coef_[0].round(3).tolist()))

    # simple lift tables for the slide/document
    lifts = []
    F["exact"] = y
    for c in cols:
        hi = F[c] > F[c].median()
        if hi.sum() < 100 or (~hi).sum() < 100:
            hi = F[c] > 0
        p_hi, p_lo = F.loc[hi, "exact"].mean(), F.loc[~hi, "exact"].mean()
        lifts.append({"feature": c, "label": FEATURE_LABELS[c], "exact_rate_high": round(p_hi, 3),
                      "exact_rate_low": round(p_lo, 3), "coef": coefs[c]})
    # quartiles of query coverage, the strongest signal
    F["cov_bin"] = pd.cut(F.query_coverage, [-0.01, 0.25, 0.5, 0.75, 1.0], labels=["0-25%", "25-50%", "50-75%", "75-100%"])
    cov = F.groupby("cov_bin", observed=False).exact.agg(["mean", "size"]).reset_index()
    insights = {
        "n_pairs": int(len(F)),
        "base_exact_rate": round(float(y.mean()), 3),
        "lifts": sorted(lifts, key=lambda d: -abs(d["coef"])),
        "coverage_bins": [{"bin": str(b), "exact_rate": round(m, 3), "n": int(n)} for b, m, n in cov.itertuples(index=False)],
        "missing_desc_share": round(float((F.desc_words == 0).mean()), 3),
        "few_bullets_share": round(float((F.n_bullets < 3).mean()), 3),
    }
    (OUT / "insights.json").write_text(json.dumps(insights, indent=2))
    print("insights written; coefs:", coefs)

    # ---------------- markets ---------------------------------------------------------
    rng = random.Random(42)
    markets = {}
    for q, meta in MARKETS.items():
        sub = df[(df["query"] == q) & (df.esci_label.isin(["Exact", "Substitute"]))]
        items = [to_listing(r) for r in sub.itertuples()]
        items = [i for i in items if i["title"] and len(i["bullets"]) + len(i["description"]) > 0]
        # dedupe titles
        seen, uniq = set(), []
        for i in items:
            k = i["title"][:60].lower()
            if k not in seen:
                seen.add(k)
                uniq.append(i)
        rng.shuffle(uniq)
        markets[q] = {"label": meta["label"], "query": q, "intents": meta["intents"],
                      "products": uniq[:COMP_PER_MARKET + 6]}
        print(q, len(uniq))
    (OUT / "markets.json").write_text(json.dumps(markets, indent=1))


if __name__ == "__main__":
    main()
