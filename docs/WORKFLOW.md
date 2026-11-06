# AgentShelf workflow

This page walks through AgentShelf from the seller's side, one screen at a time, then gives a short script for a live demo. No technical background needed.

---

## Meet the user

**Maria sells air purifiers on Amazon.** She has six products and no marketing team. Sales slipped this year, and her ads haven't changed. More of her customers now ask an AI assistant to "find me a good air purifier for a bedroom" and let it choose. Maria has no way to see how those assistants judge her listing.

## The journey

### Before you start: settings (left sidebar)

- **Shopping agent:** *Claude agent* uses Claude to play the AI shopper (needs an API key). *Proxy agent* is a built-in offline shopper: instant, free, and fully transparent.
- **Product category:** the shelf to compete on. Each category holds real Amazon listings from the same search.
- **Runs per shopper request:** how many times each shopper visits the shelf. More runs give steadier numbers.

### Step 1 · Your listing

Pick a real listing to start from, or paste your own title, bullets, description and price into the boxes. The **competing listings** (7 real products from the same Amazon search) are listed underneath, so you can see who you're up against.

### Step 2 · Agent-readiness audit

A score from 0 to 100, compared with the shelf average and the best competitor. It is made of five checks:

| Check | Plain-English question | Points |
|---|---|---|
| Matches what shoppers ask for | Does your listing use the words real shoppers use? | 25 |
| Measurable specs | Do you give numbers (square feet, decibels, hours, pounds)? | 20 |
| Key attributes stated | Do you say the size, weight, materials, who it's for, warranty, safety, and what's in the box? | 20 |
| Structure | A clear title, at least 5 bullets, a real description? | 20 |
| Facts over fluff | Do you rely on "best", "premium" and "amazing", which agents ignore? | 15 |

Next to the score is a list of issues ranked by importance (🔴 high, 🟠 medium, ⚪ low).

### Step 3 · Send AI shoppers to the shelf

You'll see four realistic shopper requests for the category, and you can edit or add your own. For example:

> *"I need an air purifier for my 300 sq ft bedroom. I have pet allergies, so it must have a true HEPA filter, and it has to be quiet enough to sleep with."*

Click **Run agent shoppers.** Each request goes to an AI shopper that sees only the product data for all 8 products, in a random order, and has to pick one and rank the rest. You get:

- **Picked by agents:** the share of shopping trips where you were chosen (your *agent pick rate*).
- **Fair share:** what you'd get by pure chance (1 in 8 = 12.5%).
- **Top-3 shortlist** and **average rank.**
- **A table, one row per shopper request,** showing your rank, which product won, and what the agent said about you, such as *"No noise level listed; user needs it quiet for sleep."*
- **Information agents wanted but could not find.** This is often the most useful line on the page.

### Step 4 · Rewrite for agents and re-test

Click **Generate agent-optimized listing.** AgentShelf writes a new version:

- The title leads with brand, product type and the two or three specs that decide the purchase.
- Each bullet starts with a short label and states one checkable fact ("Coverage: up to 300 sq ft").
- A table of structured attributes is added.
- Marketing fluff is removed.
- **No new facts are invented.** Anything shoppers need that your listing doesn't say goes onto a **Seller to-do** list.

The **same shoppers then visit the same shelf again**, and a green bar shows before → after for pick rate, shortlist, rank and readiness score.

### Step 5 · Fill the gaps, then re-test

The to-do list turns into a short form ("Warranty / returns", "Size / dimensions / capacity", ...). Fill in what you know and click **Re-test with my answers.** The bar now shows three stages: original → rewritten → rewritten plus your facts.

Finally, **Download rewritten listing (JSON)** gives you the new copy to paste into Seller Central after you review it.

### The other tabs

- **Market evidence (ESCI data):** what 40,000 real Amazon search results say about which listings are judged relevant, plus a check that our simulated shopper behaves sensibly.
- **How it works:** a one-page summary of the method.

---

## Three-minute demo script

| Time | Say | Do |
|---|---|---|
| 0:00 | "When an AI does the shopping, your listing is your only salesperson, and you can't see it losing." | Show the title screen |
| 0:20 | "This is a real air purifier listing from Amazon, on a shelf with 7 real competitors." | Step 1, open the competitors list |
| 0:40 | "First a checkup: 60 out of 100. It never states a warranty, size or what's in the box." | Step 2 |
| 1:00 | "Now we send four real shopper requests to AI shopping agents." | Step 3: click **Run agent shoppers** |
| 1:20 | "Agents picked it 16% of the time. Here's what they said, and what they couldn't find." | Point at the table and the missing-info line |
| 1:45 | "One click rewrites it using only facts already in the listing, then the same agents shop again." | Step 4: click **Generate** and read the green bar |
| 2:15 | "The tool says agents keep asking for warranty and room size. The seller fills those in." | Step 5: type two answers, click **Re-test** |
| 2:35 | "16% → 51%. That's the KPI we'd monitor for a seller every week." | Point at the final bar |
| 2:50 | "And it's grounded in data: covering shoppers' words lifts Amazon's exact-match rate from 37% to 84%." | Market evidence tab |

**Backup plan:** if the internet or API is down, switch the sidebar to **Proxy agent (offline).** The whole demo runs locally.
