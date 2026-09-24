"""Audit category assignment across the whole catalogue.

Prints, per category, how many products landed there and a random sample of
their names — plus the size of the "Other" bucket, which is the honest measure
of how much vocabulary we are still missing.

    python audit_categories.py            # sample every category
    python audit_categories.py rice 20    # 20 samples from one category
"""

from __future__ import annotations

import random
import sys
from collections import Counter

from sqlalchemy import select

from app.db import SessionLocal
from app.matching.brands import learn_brands
from app.matching.categories import LABELS, categorise
from app.matching.normalize import parse_title
from app.models import Offer

only = sys.argv[1] if len(sys.argv) > 1 else None
sample_size = int(sys.argv[2]) if len(sys.argv) > 2 else 12

with SessionLocal() as session:
    vocab = learn_brands(session)
    titles = list(session.scalars(select(Offer.title)))

buckets: dict[str, list[str]] = {}
counts: Counter[str] = Counter()
unknown_tokens: Counter[str] = Counter()

for title in titles:
    parsed = parse_title(title, None, vocab)
    if not parsed.tokens:
        continue
    slug, _label = categorise(parsed.tokens)
    counts[slug] += 1
    buckets.setdefault(slug, []).append(title)
    if slug == "other":
        unknown_tokens.update(parsed.tokens)

total = sum(counts.values())
random.seed(0)

print(f"{total} titles categorised\n")
for slug, count in counts.most_common():
    if only and slug != only:
        continue
    share = count / total * 100
    print(f"=== {LABELS.get(slug, slug)} ({slug}) — {count} ({share:.1f}%) ===")
    for name in random.sample(buckets[slug], min(sample_size, len(buckets[slug]))):
        print(f"    {name[:86]}")
    print()

if not only:
    print(f"Other bucket: {counts['other']} ({counts['other'] / total * 100:.1f}%)")
    print("Most common tokens with no category rule:")
    for token, n in unknown_tokens.most_common(30):
        print(f"    {token:18} {n}")
