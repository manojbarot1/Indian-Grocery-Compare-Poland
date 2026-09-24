# DesiPrice

**Price comparison for Indian groceries in Poland** — a Ceneo for atta, dal and masala.

Eleven shops sell the same 10 kg bag of Aashirvaad atta. One charges 69.50 zł,
another 78.00 zł. Nobody compares them, because every shop writes the product
name differently — in Polish, English, or Hindi transliteration — and no
comparison site covers this market.

This does.

```
Aashirvaad Whole Wheat Atta 10 kg          Maggi 2-Minute Masala Noodles 70 g
  AsianShop            69.50 zł              India Bazaar          2.99 zł
  India Da Bazaar      73.00 zł              Grocerywala           3.49 zł
  India Bazaar         77.99 zł              Indian Supermart      4.00 zł
  India@Store          77.99 zł
  Indian Supermart     78.00 zł
  Little India         78.00 zł
```

<sub>Real figures from the live index, captured 18 September 2026. Shop prices
change — these illustrate the spread, they are not a current quote.</sub>

---

## Status

Working MVP, running against live shop catalogues. Figures below are a
snapshot from 18 September 2026.

| | |
|---|---|
| Offers ingested | **11,586** |
| Shops | **11** (Poland only) |
| Canonical products | **9,108** |
| Sold by 2+ shops | **965** |
| Categories | 16 aisles, ~70 sub-categories |
| Tests | **84** passing |

---

## What it does

**Every shop's price, on every product.** The comparison *is* the product, so
it sits on the card rather than behind a click. One row per shop, cheapest
first, with a saving banner when there's a real choice to make.

**Honest prices.** Product prices only. Delivered cost was built, tried, and
removed: only two of eleven shops publish real shipping rates, so most
"delivered" figures were estimates sitting next to real prices — precision that
wasn't there. Published free-delivery thresholds *are* shown, because those are
facts that change decisions.

**Cross-language matching.** `Mąka pszenna razowa Aashirvaad Atta 10 kg` and
`Aashirvaad Whole Wheat Flour (Atta) 10Kg` are the same bag. The matcher knows
that. So does `haldi` ↔ `turmeric`, `sabudana` ↔ `sago`, `mąka` ↔ `flour`.

**Basket optimiser.** Buying each item wherever it's cheapest looks optimal
until you pay shipping four times. This is where delivery genuinely belongs —
thresholds are real and apply per order:

| Strategy | Parcels | Total |
|---|---|---|
| Cheapest price per item | 2 | 46.93 zł |
| **Optimal split** | **1** | **32.94 zł** |

<sub>A real five-item basket, same snapshot.</sub>

The optimiser is exact, not greedy — it enumerates shop subsets, which is
instant for the handful of shops serving one market. A greedy answer that's
4 zł worse would undermine the premise of the site.

**Price per kg, properly.** 500 g / 1 kg / 5 kg are never conflated, and a
`5kg X3 COMBO` is a different product from a 5 kg bag.

---

## Quick start

Everything runs in Docker. Your host needs no Python, Node or Postgres.

```bash
git clone https://github.com/manojbarot1/Indian-Grocery-Compare-Poland.git
cd Indian-Grocery-Compare-Poland
docker compose up -d
```

| | |
|---|---|
| Web app | http://localhost:5173 |
| API docs | http://localhost:8090/docs |
| Zero-build UI (no Node needed) | http://localhost:8090 |

The database starts empty. Fill it:

```bash
docker compose exec api python cli.py refresh
```

That pulls every shop catalogue and matches them. API-based shops take seconds;
the HTML-crawled ones take longer because they're polled at one request per
second. Testing on a phone on the same Wi-Fi? Use your machine's LAN IP:
`http://192.168.x.x:5173`.

---

## Architecture

```
shops.yaml ──► ingest adapters ──► offers ──► matcher ──► products
                shopify │ woo │ html            │             │
                                         brand learning    categories
                                                              │
                                    search API ◄──────────────┤
                                    basket optimiser ◄────────┘
```

| Path | Role |
|---|---|
| `backend/shops.yaml` | Shop registry — how to ingest, how shipping is priced |
| `backend/app/ingest/` | Platform adapters + upsert runner with price history |
| `backend/app/matching/normalize.py` | Title → brand, canonical tokens, pack size |
| `backend/app/matching/brands.py` | Learns the brand vocabulary from the corpus |
| `backend/app/matching/matcher.py` | Multi-key blocking + conservative scoring |
| `backend/app/matching/categories.py` | Category and sub-category taxonomy |
| `backend/app/basket/optimizer.py` | Exact cheapest split across shops |
| `backend/app/shipping/engine.py` | Weight bands, free-over thresholds |
| `frontend/` | React + TypeScript + Vite |

**Stack:** FastAPI · SQLAlchemy 2 · PostgreSQL · React 18 · TypeScript · Vite · Docker

---

## The interesting part: matching

Collapsing eleven catalogues into one product list is the whole problem. Three
approaches were tried before one worked.

**Blocking.** Comparing every offer against every other is O(n²) and pointless;
comparing only exact-key matches misses almost everything, because
`Heera Basmati Rice 1kg` and `Heera Brown Basmati Rice 1 KG` never produce the
same single key. Each offer emits several keys built from its *rarest* tokens,
always pinned to pack size. Any product sharing any key becomes a candidate.

**Scoring is deliberately conservative.** A wrong merge shows a shopper a price
for something they can't buy; a missed merge just looks like two products.
Brand or size disagreement is disqualifying. Variant words are decisive —
`Mild` never merges with `Hot`, `Chickpeas` never with `Brown Chickpeas`, and a
`Damaged Packaging` listing never sets the headline price for the good one.

**`token_set_ratio` was tried and rejected.** It scores a subset as a perfect
match, so `Coriander Seeds` merged with `Sesame Seeds` on the shared word
"seed". Similarity now blends order-free string distance with **idf-weighted
token overlap**, so the distinctive words that differ are the ones that count.

**Brands are learned, not listed.** A curated list never keeps up with the long
tail — Weikfield, Annam, Melam, Talod. Titles are overwhelmingly
`<Brand> <product> <size>`, so a token leading many distinct titles across
shops is a brand.

Leading-token frequency alone isn't enough, though. So many titles start with
"Garam Masala …" that **`garam` was being learned as a brand**, which demoted
the real brand (TRS) to an ordinary token and split the product across every
shop. A brand is followed by whatever it happens to sell; a compound head-noun
is followed by the same word nearly every time. Candidates whose dominant
follower is itself a common word are now rejected.

The same class of bug bit twice more, both caught from real listings:

- **`maka pszenna`** ("wheat flour" in Polish) became a brand, so Schani atta
  and Aashirvaad atta looked like the same maker and merged — a 44 zł bag shown
  as a 78 zł one. Every word in a candidate brand must now be brand-ish, not
  just the token as a whole.
- **`Select Sharbati`** merged into plain `Aashirvaad Atta` because the shorter
  title is contained in the longer one. Containment now only applies when the
  extra words are vocabulary we recognise, or common enough not to be a product
  line. Measured on the live catalogue, descriptors sit at idf 3.9–5.3 and
  variety names at 8.7–9.4.

---

## Categories

Shop-supplied categories are useless: every shop names them differently
(`MĄKA`, `Flour, Grain & Pulses`, `Kasze i zboża`), many supply none, and the
HTML-crawled shops have no category data at all.

Instead categories are derived from the canonical tokens the matcher already
produces — language-normalised, so a Polish listing and an English one land in
the same aisle with no per-shop mapping.

Rules carry tiers, because **what a product *is* beats what it's *made of***:

```
INGREDIENT  <  PREPARED  <  STRONG  <  NONFOOD
"atta"         "noodle"     "tea"      "ceramic bowl"
```

Without that, `Maggi Atta Noodles` filed under Flour & Atta. With it, a
ceramic "sauce bowl" stops being a sauce and `BRU Instant Coffee` stops being a
mix.

Sub-categories split the big aisles one level down — 201 products in
"Flour & Atta" is a list, not a filter:

> **Flour & Atta** → Wheat Atta · Besan / Gram Flour · Semolina / Sooji ·
> Maida · Rice Flour · Corn Flour · Millet Flour

There's an audit tool for this, because hand-written taxonomies drift:

```bash
docker compose exec api python audit_categories.py              # every aisle
docker compose exec api python audit_categories.py atta-flour 30 # one aisle
```

It categorises all 11,586 titles, samples each bucket, and lists the most
common tokens that match no rule — which is how the misfits above were found.

---

## Shops

| Shop | Platform | Ingest route | Shipping data |
|---|---|---|---|
| India Bazaar | Shopify | `/products.json` | **published** |
| AsianShop | Shoper | category crawl + JSON-LD | **published** |
| India@Store | Shopify | `/products.json` | partial |
| Indian Corner | bespoke | sitemap + CSS selectors | partial |
| Little India | SOTESHOP | category crawl | checkout only |
| Oriental Market | WooCommerce | Store API | checkout only |
| Grocerywala | Shopify | `/products.json` | checkout only |
| Asia Deli | Shopify | `/products.json` | checkout only |
| Indian Supermart | WooCommerce | Store API | checkout only |
| Little Asia Grocery | WooCommerce | Store API | checkout only |
| India Da Bazaar | WooCommerce | Store API | checkout only |

Dookan (Netherlands) is configured but disabled — this index is Poland-only.

### Three adapters

- **Shopify** `/products.json` — gives per-variant `grams`, so parcel weight is
  real rather than guessed. Each variant is its own offer.
- **WooCommerce** `/wp-json/wc/store/v1/products` — prices arrive as integer
  minor units (`"7500"` = 75.00 zł), and `weight` is in whatever unit the shop
  configured, which the API never tells you; the shop entry declares it.
- **`html`** — generic crawler for shops with no API. Discovers products from a
  sitemap, or by walking the category tree when the sitemap is missing or
  stale. Extracts via schema.org JSON-LD first, falling back to per-shop CSS
  selectors.

Adding a shop is usually a YAML entry, not code.

### Things the HTML adapter learned the hard way

- **Don't infer stock from page text.** These storefronts ship a hidden
  "Brak w magazynie" modal on *every* product page, which marked an entire
  catalogue unavailable. Stock defaults to available, overridden only by an
  explicit per-shop selector.
- **Recover pack size from the URL slug.** A page titled "TRS Gruba semolina"
  at `/product/trs-coarse-semolina-500g-…` has no size in the title — and pack
  size is part of product identity.
- **Stitch fragmented JSON-LD.** Shoper splits one product across a dozen
  `<script>` tags that each carry a fragment, all sharing an `@id`. Read
  individually, every one looks empty.

### Placeholder prices

One shop listed 78 unrelated products at exactly 1.00 zł — mango, moong dal,
whole black pepper. Their API reports it faithfully, so it's their data, not a
parsing bug. Ingested as-is, that shop would win every comparison it appeared
in with a price nobody can buy at.

Detected rather than hard-coded: a *specific* low value repeated across a
meaningful share of one catalogue is a placeholder. A shop genuinely selling
cheap things spreads across 0.99 / 1.00 / 1.20 — it doesn't stack 78 unrelated
products on one value.

---

## Operations

```bash
docker compose exec api python cli.py refresh            # ingest + match
docker compose exec api python cli.py ingest --shop asianshop
docker compose exec api python cli.py stats
docker compose exec api python cli.py inspect "Daawat Basmati Rice 1kg"
docker compose exec api python cli.py basket 20507:2 20187:1
docker compose exec api python -m pytest tests -q
```

`inspect` is the fastest way to debug a bad match — it shows exactly how a
title normalises and what else shares its blocking key.

Use `cli.py reset-matches` rather than touching tables by hand:
`TRUNCATE products CASCADE` silently takes `offers` with it.

---

## Known limitations

Worth knowing before building on this.

- **Shipping is published by only 2 of 11 shops.** The rest quote at checkout.
  Estimates are used solely inside the basket optimiser and are labelled there.
- **"Other" is ~21% of products** — mostly one shop's Japanese/Korean range and
  long-tail brand names. Real remaining work; `audit_categories.py` shows what's
  falling through.
- **Match recall is deliberately conservative.** More genuine matches exist than
  are merged. Loosening the threshold finds them at the cost of false merges —
  the wrong trade for a site whose only asset is trust in its prices.
- **No scheduled refresh.** Prices are as fresh as the last `cli.py refresh`.
  The ingest layer is idempotent and records price history, so this is mostly a
  cron entry away.
- **Static FX rates** in `config.py`, used only if a shop prices in a foreign
  currency.
- **No admin UI** for overriding matches. The `match_locked` flag exists for
  exactly this and is never overwritten by the matcher, but nothing sets it yet.
- **Schema changes use `create_all`**, not migrations. Fine now; needs Alembic
  before there's data worth keeping.

---

## Ethics and etiquette

This reads other people's shops, so it does so carefully:

- One request per second, and each shop's own `Crawl-delay` is honoured.
- Only public endpoints that `robots.txt` permits — checked per shop.
- The crawler identifies itself with a contact URL in the User-Agent.
- A failed page is skipped, never retried in a loop.
- Prices link straight back to the shop. The point is to send them traffic.

Comparison sites normally operate through affiliate programmes. Approaching
these shops directly turns a grey area into a revenue stream, and is the
intended next step rather than an afterthought.

---

## Roadmap

1. Nightly refresh + price-drop alerts — the `price_points` table already
   supports history charts.
2. Shrink the "Other" bucket; more sub-category coverage.
3. Checkout-probe shipping for the shops that quote only at checkout.
4. Affiliate arrangements with the listed shops.
5. Multi-country — `ships_to` and per-country shipping already exist in the
   model; the UI needs a country picker.

---

## Licence

MIT — see [LICENSE](LICENSE).

Product names, trademarks and prices belong to the respective shops and brands.
