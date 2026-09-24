"""Collapse many shop offers into canonical products.

The hard part is candidate generation. Comparing every offer against every other
is 6k^2 and pointless; comparing only exact-key matches misses almost everything,
because "Heera Basmati Rice 1kg" and "Heera Brown Basmati Rice 1 KG" never
produce the same single key.

So we use multi-key blocking: each offer emits several keys, and any product
sharing *any* key becomes a candidate. Every key pins the pack size, because a
500 g and a 1 kg bag are genuinely different products no matter how similar the
names are. Scoring then decides.

Scoring is deliberately conservative. A wrong merge is much worse than a missed
one: it shows a shopper a price for something they cannot actually buy. Missed
merges just look like two separate products until someone fixes them in admin.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from rapidfuzz import fuzz
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Offer, Product
from .brands import is_product, learn_brands
from .categories import categorise, subcategorise
from .normalize import (
    CANONICAL_TOKENS,
    HARD_DISCRIMINATOR_GROUPS,
    SOFT_DISCRIMINATOR_GROUPS,
    ParsedTitle,
    apply_size,
    parse_title,
    resolve_size,
)

MAX_BLOCK_KEYS = 4
"""How many token keys one record emits. More keys = better recall, bigger blocks."""


@dataclass
class Candidate:
    product: Product
    score: float


def size_tag(parsed: ParsedTitle) -> str:
    if parsed.size.base_value and parsed.size.base_unit:
        return f"{parsed.size.base_value:g}{parsed.size.base_unit}"
    return "_"


def product_size_tag(product: Product) -> str:
    if product.size_value and product.base_unit:
        return f"{product.size_value:g}{product.base_unit}"
    return "_"


def blocking_keys(
    brand: str | None, tokens: list[str], size: str, rarity: dict[str, float]
) -> list[str]:
    """Keys under which this record is indexed and looked up.

    Rare tokens make far better keys than common ones: "basmati" splits the
    catalogue usefully, "rice" does not.
    """
    keys: list[str] = []
    if brand:
        keys.append(f"b:{brand}|{size}")
    distinctive = sorted(tokens, key=lambda t: -rarity.get(t, 10.0))[:MAX_BLOCK_KEYS]
    for token in distinctive:
        keys.append(f"t:{token}|{size}")
        if brand:
            keys.append(f"bt:{brand}:{token}|{size}")
    return keys or [f"_|{size}"]


DEFAULT_IDF = 8.0
"""Weight for a token we have never seen — treat the unknown as distinctive."""


def weighted_jaccard(a: set[str], b: set[str], rarity: dict[str, float]) -> float:
    """Token overlap weighted by how distinctive each token is.

    This is what stops "Coriander Seeds" merging with "Sesame Seeds": they share
    only "seed", which is common and therefore nearly weightless, while
    "coriander" and "sesame" are rare and both go unmatched.
    """
    if not a or not b:
        return 0.0
    intersection = sum(rarity.get(t, DEFAULT_IDF) for t in a & b)
    union = sum(rarity.get(t, DEFAULT_IDF) for t in a | b)
    return intersection / union if union else 0.0


RARE_DOC_FREQUENCY = 4
"""A token in fewer than this many titles counts as near-unique."""


def rare_idf_cutoff(document_count: int) -> float:
    """idf above which an unrecognised token is treated as a variety name.

    Expressed as a document frequency so it scales with the catalogue: idf is
    log(N/df), so this is simply "appears in fewer than RARE_DOC_FREQUENCY
    titles".
    """
    return math.log(max(document_count, RARE_DOC_FREQUENCY) / RARE_DOC_FREQUENCY)


def score(
    parsed: ParsedTitle,
    product: Product,
    rarity: dict[str, float],
    rare_idf: float = 8.0,
) -> float:
    """0..1 similarity between a parsed offer title and a canonical product."""
    # Brand disagreement is disqualifying — Heera cumin is not TRS cumin.
    if parsed.brand and product.brand and parsed.brand != product.brand:
        return 0.0

    # Size disagreement is disqualifying beyond a 2% tolerance (rounding only).
    if parsed.size.base_value and product.size_value:
        if parsed.size.base_unit != product.base_unit:
            return 0.0
        larger = max(parsed.size.base_value, product.size_value)
        if abs(parsed.size.base_value - product.size_value) / larger > 0.02:
            return 0.0

    offer_tokens = set(parsed.tokens)
    product_tokens = set((product.match_core or "").split())

    # Variant words are decisive. Disagreeing inside any group means different
    # products. A one-sided word is decisive only for HARD groups; for SOFT
    # ones it is usually just a terser shop title.
    variant_penalty = 0.0
    hard_mismatch = False
    for group in HARD_DISCRIMINATOR_GROUPS:
        left, right = offer_tokens & group, product_tokens & group
        if left and right and left != right:
            return 0.0
        if bool(left) != bool(right):
            variant_penalty += 0.15
            hard_mismatch = True
    for group in SOFT_DISCRIMINATOR_GROUPS:
        left, right = offer_tokens & group, product_tokens & group
        if left and right and left != right:
            return 0.0
        if bool(left) != bool(right):
            variant_penalty += 0.08

    # Compare like with like: the product's own canonical tokens, not its
    # display name, which has brand and size baked back into it.
    #
    # Deliberately NOT token_set_ratio: it scores a subset as a perfect match,
    # so "good day biscuit" would score 1.0 against "good day biscuit pistachio
    # almond". The distinctive words that differ are exactly what must count,
    # which is what the idf-weighted overlap term measures.
    order_free = fuzz.token_sort_ratio(parsed.core, product.match_core) / 100.0
    overlap = weighted_jaccard(offer_tokens, product_tokens, rarity)
    name_score = 0.5 * order_free + 0.5 * overlap - variant_penalty

    # Shops describe the same bag at very different lengths: "Aashirvaad Atta
    # 10kg" against "Aashirvaad Whole Wheat Flour (Atta) 10Kg". Jaccard
    # punishes the verbose one for words the terse one simply omits, so when
    # the shorter description is fully contained in the longer we score that
    # containment instead.
    #
    # Only when brand AND size already agree. Those two are strong identity
    # anchors; without them containment would merge "Rice" into "Basmati Rice".
    # A hard variant word on one side blocks this path entirely: containment
    # assumes the extra words are noise, which is exactly false for "multigrain",
    # "brown" or "damaged".
    anchored = (
        not hard_mismatch
        and parsed.brand
        and product.brand
        and parsed.brand == product.brand
        and parsed.size.base_value
        and product.size_value
    )
    if anchored and offer_tokens and product_tokens:
        smaller, larger = (
            (offer_tokens, product_tokens)
            if len(offer_tokens) <= len(product_tokens)
            else (product_tokens, offer_tokens)
        )
        # Blocked when the longer title adds a word that is both unrecognised
        # and near-unique. Measured on the live catalogue, canonical descriptors
        # sit at idf 3.9-5.3 ("whole", "flour", "atta", "wheat"), ordinary
        # product words at 5.5-7.4 ("king", "chapati", "cashew"), and variety
        # names far above: "select" 8.7, "sharbati" 9.4. Those last are where
        # product lines hide — treating them as noise merged a 77.99 zł bag with
        # a 99.99 zł premium one.
        #
        # Requiring *every* extra word to be canonical was tried and was far too
        # strict: it cost 124 good merges to fix that one.
        extra = larger - smaller
        blocking = {
            t
            for t in extra
            if t not in CANONICAL_TOKENS and rarity.get(t, DEFAULT_IDF) >= rare_idf
        }
        if not blocking:
            smaller_weight = sum(rarity.get(t, DEFAULT_IDF) for t in smaller)
            if smaller_weight:
                containment = (
                    sum(rarity.get(t, DEFAULT_IDF) for t in smaller & larger)
                    / smaller_weight
                )
                name_score = max(name_score, containment - variant_penalty)

    bonus = 0.0
    if parsed.brand and product.brand and parsed.brand == product.brand:
        bonus += 0.08
    elif bool(parsed.brand) != bool(product.brand):
        bonus -= 0.06
    if parsed.size.base_value and product.size_value:
        bonus += 0.06
    if bool(parsed.size.base_value) != bool(product.size_value):
        bonus -= 0.10

    return max(0.0, min(1.0, name_score + bonus))


def _unique_slug(session: Session, base: str, taken: set[str]) -> str:
    slug = base or "product"
    suffix = 2
    while slug in taken or session.scalar(select(Product.id).where(Product.slug == slug)):
        slug = f"{base}-{suffix}"
        suffix += 1
    taken.add(slug)
    return slug


def display_name(offer: Offer, parsed: ParsedTitle) -> str:
    parts = [parsed.brand.title()] if parsed.brand else []
    parts.append(" ".join(parsed.tokens).title() or offer.title)
    if parsed.size.value and parsed.size.unit:
        qty = f"{parsed.size.value:g}{parsed.size.unit}"
        parts.append(
            f"{parsed.size.multipack}x{qty}" if parsed.size.multipack > 1 else qty
        )
    return " ".join(parts).strip()


def create_product(
    session: Session, offer: Offer, parsed: ParsedTitle, taken: set[str]
) -> Product:
    name = display_name(offer, parsed)
    # Use the same resolved size the offer carries, including the shop-weight
    # fallback. Otherwise the offer has a unit price in kg while the product
    # records no unit at all, and the UI renders "427.00 zł/".
    size = resolve_size(parsed, offer.weight_grams)
    category_slug, _label = categorise(parsed.tokens)
    subcategory_slug = subcategorise(category_slug, parsed.tokens)
    product = Product(
        slug=_unique_slug(session, slugify(name)[:200], taken),
        name=name,
        brand=parsed.brand,
        category=category_slug,
        subcategory=subcategory_slug,
        image_url=offer.image_url,
        size_value=size.base_value,
        size_unit=size.unit,
        base_unit=size.base_unit,
        match_key=parsed.match_key,
        match_core=parsed.core,
    )
    session.add(product)
    session.flush()
    return product


def token_rarity(parsed_titles: list[ParsedTitle]) -> dict[str, float]:
    """Inverse document frequency per token, used to pick good blocking keys."""
    counts: Counter[str] = Counter()
    for parsed in parsed_titles:
        counts.update(set(parsed.tokens))
    total = max(len(parsed_titles), 1)
    return {token: math.log(total / count) for token, count in counts.items()}


def match_offers(session: Session, rematch_all: bool = False) -> dict[str, int]:
    """Assign every offer to a canonical product, creating products as needed.

    Offers with `match_locked` are never touched — that flag is how a human
    overrides the algorithm permanently.

    Brands are learned from the whole corpus here rather than at ingest time,
    because a brand is only recognisable once you have seen the other shops.
    """
    vocab = learn_brands(session)

    stmt = select(Offer).where(Offer.match_locked.is_(False))
    if not rematch_all:
        stmt = stmt.where(Offer.product_id.is_(None))
    offers = list(session.scalars(stmt))

    # Pass 1: parse everything, so token rarity is known before we block.
    parsed_by_offer: dict[int, ParsedTitle] = {}
    usable: list[Offer] = []
    skipped = 0
    for offer in offers:
        if not is_product(offer.title):
            skipped += 1
            continue
        vendor = (offer.raw or {}).get("vendor")
        parsed = parse_title(offer.title, vendor, vocab)
        if not parsed.tokens:
            skipped += 1
            continue
        parsed_by_offer[offer.id] = parsed
        usable.append(offer)

    rarity = token_rarity(list(parsed_by_offer.values()))
    rare_idf = rare_idf_cutoff(len(parsed_by_offer))

    # Index existing products under every key they can be found by.
    blocks: dict[str, list[Product]] = defaultdict(list)

    def index(product: Product) -> None:
        tokens = product.match_core.split() if product.match_core else []
        for key in blocking_keys(product.brand, tokens, product_size_tag(product), rarity):
            blocks[key].append(product)

    for product in session.scalars(select(Product)):
        index(product)

    # Process the biggest catalogues first so canonical names come from the
    # shops with the most complete titles.
    usable.sort(key=lambda o: (o.shop_id, o.title))

    stats = {"matched": 0, "created": 0, "skipped": skipped, "brands": len(vocab)}
    taken_slugs: set[str] = set()

    for offer in usable:
        parsed = parsed_by_offer[offer.id]
        offer.brand = parsed.brand  # corpus vocabulary beats the ingest guess
        offer.match_key = parsed.match_key
        apply_size(offer, parsed)

        keys = blocking_keys(parsed.brand, parsed.tokens, size_tag(parsed), rarity)
        seen: set[int] = set()
        best: Candidate | None = None
        for key in keys:
            for product in blocks.get(key, ()):
                if product.id in seen:
                    continue
                seen.add(product.id)
                value = score(parsed, product, rarity, rare_idf)
                if best is None or value > best.score:
                    best = Candidate(product, value)

        if best and best.score >= settings.match_threshold:
            offer.product_id = best.product.id
            offer.match_score = round(best.score, 4)
            stats["matched"] += 1
            if not best.product.image_url and offer.image_url:
                best.product.image_url = offer.image_url
        else:
            product = create_product(session, offer, parsed, taken_slugs)
            index(product)
            offer.product_id = product.id
            offer.match_score = 1.0
            stats["created"] += 1

    session.commit()
    return stats


def prune_orphan_products(session: Session) -> int:
    """Drop canonical products that no longer have any offers."""
    orphans = list(
        session.scalars(
            select(Product).where(~Product.offers.any())  # type: ignore[arg-type]
        )
    )
    for product in orphans:
        session.delete(product)
    session.commit()
    return len(orphans)
