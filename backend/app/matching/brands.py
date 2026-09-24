"""Learn the brand vocabulary from the catalogue instead of hard-coding it.

A curated brand list is always out of date — Indian grocery has a long tail of
regional brands (Annam, Weikfield, Melam, Talod...) and no list will keep up.

But the data tells us: Indian grocery titles are overwhelmingly written as
"<Brand> <product> <size>", so a token that starts many *different* titles, in
more than one shop, and is not itself a product word, is almost certainly a
brand. That signal is strong and self-maintaining.

The curated set in normalize.BRANDS stays as a seed: it handles multi-word
brands and aliases ("Haldiram's" -> haldiram) that frequency alone would miss.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Offer, Shop
from .normalize import BRANDS, STOPWORDS, SYNONYMS, basic_clean, strip_accents

MIN_TITLES = 4
"""A candidate must lead at least this many distinct titles."""

MIN_LENGTH = 3

# Words that lead many titles but are descriptions, not brands.
NOT_BRANDS = {
    "fresh", "frozen", "organic", "indian", "premium", "whole", "ground",
    "roasted", "dried", "raw", "pure", "natural", "special", "instant",
    "ready", "hot", "sweet", "green", "red", "white", "black", "brown",
    "baby", "mini", "big", "small", "large", "extra", "new", "classic",
    "traditional", "homemade", "handmade", "original", "assorted", "mixed",
    "gift", "combo", "value", "family", "pack", "box", "set", "delivery",
    "shipping", "free", "sample", "test", "unknown", "brand", "no",
    # Indian product head-words that frequently lead a title but name the food,
    # not the maker. "Garam Masala" starts hundreds of titles; treating "garam"
    # as a brand demotes the real brand to an ordinary token and splits the
    # product across every shop that words it differently.
    "garam", "masala", "curry", "biryani", "tandoori", "basmati", "madras",
    "kashmiri", "deggi", "pani", "puri", "tikka", "korma", "vindaloo",
    "samosa", "pakora", "idli", "dosa", "upma", "halwa", "barfi", "jamun",
    "lassi", "raita", "naan", "roti", "chapati", "paratha", "achar",
}


def _lead_tokens(title: str) -> tuple[str | None, str | None]:
    """First and first-two tokens of a title, e.g. 'organic india tulsi'
    -> ('organic', 'organic india')."""
    cleaned = basic_clean(title)
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return None, None
    first = parts[0]
    second = f"{parts[0]} {parts[1]}" if len(parts) > 1 else None
    return first, second


def _plausible(token: str) -> bool:
    if len(token.replace(" ", "")) < MIN_LENGTH:
        return False
    if token in STOPWORDS or token in SYNONYMS or token in NOT_BRANDS:
        return False
    # Every word must be brand-ish, not just the token as a whole. Checking only
    # the tail let "maka pszenna" ("wheat flour") become a brand, which gave
    # every Polish flour listing the same fake brand — so Schani atta and
    # Aashirvaad atta looked like the same maker and got merged.
    if any(part in NOT_BRANDS or part in SYNONYMS for part in token.split()):
        return False
    if re.search(r"\d", token):
        return False
    return bool(re.fullmatch(r"[a-z][a-z' -]*", token))


def learn_brands(session: Session) -> set[str]:
    """Mine brand names out of the offer corpus."""
    shop_names = {
        strip_accents(name or "").lower()
        for name in session.scalars(select(Shop.name))
    }

    unigram_titles: dict[str, set[str]] = defaultdict(set)
    bigram_titles: dict[str, set[str]] = defaultdict(set)
    unigram_shops: dict[str, set[int]] = defaultdict(set)
    vendor_titles: dict[str, set[str]] = defaultdict(set)
    followers: dict[str, Counter[str]] = defaultdict(Counter)
    token_frequency: Counter[str] = Counter()

    for title, shop_id, vendor in session.execute(
        select(Offer.title, Offer.shop_id, Offer.brand)
    ):
        first, second = _lead_tokens(title or "")
        key = basic_clean(title or "")
        token_frequency.update(set(key.split()))
        if first:
            unigram_titles[first].add(key)
            unigram_shops[first].add(shop_id)
            parts = key.split()
            if len(parts) > 1:
                followers[first][parts[1]] += 1
        if second:
            bigram_titles[second].add(key)
        if vendor:
            v = basic_clean(vendor)
            if v and v not in shop_names:
                vendor_titles[v].add(key)

    def is_compound_head(token: str) -> bool:
        """True when `token` is the first half of a fixed phrase rather than a
        brand — "garam" is nearly always followed by "masala", whereas a real
        brand is followed by whatever it happens to sell.

        Requiring the dominant follower to itself be a common word keeps small
        brands with one hero product from being rejected.
        """
        counts = followers.get(token)
        total = sum(counts.values()) if counts else 0
        if total < MIN_TITLES:
            return False
        follower, count = counts.most_common(1)[0]
        return count / total > 0.6 and token_frequency[follower] >= 20

    learned: set[str] = set()

    def qualifies_alone(token: str) -> bool:
        if not _plausible(token) or token in shop_names:
            return False
        if is_compound_head(token):
            return False
        # Either it leads plenty of titles, or it appears in more than one shop
        # (cross-shop agreement is a strong brand signal).
        return len(unigram_titles[token]) >= MIN_TITLES or (
            len(unigram_shops[token]) > 1 and len(unigram_titles[token]) >= 2
        )

    for token in unigram_titles:
        if qualifies_alone(token):
            learned.add(token)

    # Two-word brands, but only where the first word cannot be the brand by
    # itself. "organic india" is real because "organic" is not a brand; but
    # "everest tandoori" is not — "everest" already stands alone, and the
    # second word is the product, not part of the name. Swallowing it would
    # split Everest's catalogue into a brand per product line.
    for token, titles in bigram_titles.items():
        head, tail = token.split()[0], token.split()[1]
        if head in learned or head in BRANDS:
            continue
        # The second word must not be the product itself: "annam garam" is
        # Annam's garam masala, not a brand called "Annam Garam".
        if tail in NOT_BRANDS or tail in SYNONYMS or is_compound_head(head):
            continue
        if len(titles) >= MIN_TITLES and _plausible(token) and token not in shop_names:
            learned.add(token)

    # A vendor field naming the same thing across several products is a brand.
    for token, titles in vendor_titles.items():
        if len(titles) >= 2 and _plausible(token):
            learned.add(token)

    return (learned | BRANDS) - shop_names


NON_PRODUCT_PATTERNS = [
    r"\bdelivery\b", r"\bshipping\b", r"\bpick-?up\b", r"\bgift card\b",
    r"\bkarta podarunkowa\b", r"\bdostawa\b", r"\bkurier\b", r"\bpaczkomat\b",
    r"\btest product\b", r"\bsample\b", r"\bdonation\b", r"\bnapiwek\b", r"\btip\b",
]
_NON_PRODUCT_RE = re.compile("|".join(NON_PRODUCT_PATTERNS), re.IGNORECASE)


def is_product(title: str) -> bool:
    """Filter out shipping fees, gift cards and other non-grocery listings that
    shops publish through the same catalogue endpoint."""
    return not _NON_PRODUCT_RE.search(strip_accents(title or "").lower())
