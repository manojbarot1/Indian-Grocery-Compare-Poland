"""Scoring rules, written from the false merges the live catalogue produced."""

from __future__ import annotations

from app.matching.brands import _plausible, is_product, learn_brands
from app.matching.matcher import score, weighted_jaccard
from app.matching.normalize import parse_title
from app.models import Offer, Product

from .conftest import make_shop

RARITY = {
    # Common words carry little weight; distinctive ones carry a lot.
    "seed": 0.5, "powder": 0.6, "masala": 0.7, "rice": 0.8, "biscuit": 0.9,
    "coriander": 5.0, "sesame": 6.0, "cumin": 5.2, "basmati": 3.0,
    "pistachio": 6.5, "almond": 6.0, "butter": 3.5, "day": 1.0, "good": 1.0,
    "chickpea": 4.0, "curry": 2.0, "madras": 4.5,
}


def product(name: str, core: str, brand=None, size=0.1, unit="kg") -> Product:
    return Product(
        id=1, slug="p", name=name, brand=brand, match_key="k",
        match_core=core, size_value=size, base_unit=unit, size_unit=unit,
    )


def test_shared_common_word_is_not_enough_to_merge():
    """'Coriander Seeds' and 'Sesame Seeds' share only 'seed'. token_set_ratio
    scored this a perfect match; the idf-weighted term must not."""
    parsed = parse_title("Annam Coriander Seeds 100g")
    other = product("RK Sesame Seeds 100g", "sesame seed white", brand=None)
    assert score(parsed, other, RARITY) < 0.72


def test_polish_tagline_listing_merges_with_a_plain_one():
    """Oriental Market titles the same tin as 'Garam Masala TRS 100g –
    Aromatyczna Przyprawa Indyjska'. It must still merge with 'TRS Garam
    Masala 100g' from another shop."""
    parsed = parse_title("Garam Masala TRS 100g – Aromatyczna Przyprawa Indyjska")
    other = product("TRS Garam Masala 100g", "garam masala", brand="trs")
    rarity = {**RARITY, "garam": 4.0, "masala": 0.7, "spice": 0.6}
    assert score(parsed, other, rarity) >= 0.72


def test_same_product_across_shops_still_merges():
    parsed = parse_title("MDH Pani Puri Masala 100g")
    other = product("MDH Pani Puri Masala 100g", "pani puri masala", brand="mdh")
    assert score(parsed, other, RARITY) >= 0.72


def test_different_flavours_do_not_merge():
    parsed = parse_title("Britannia Good Day Butter Biscuit 72g")
    other = product(
        "Good Day Pistachio Almond", "good day pistachio almond biscuit",
        brand="britannia", size=0.072,
    )
    assert score(parsed, other, RARITY) < 0.72


def test_heat_level_is_disqualifying():
    parsed = parse_title("TRS Madras Curry Powder Mild 100g")
    other = product(
        "TRS Madras Curry Powder Hot", "madras curry powder hot", brand="trs"
    )
    assert score(parsed, other, RARITY) == 0.0


def test_colour_variant_does_not_merge():
    parsed = parse_title("TRS Chickpeas 1kg")
    other = product("TRS Brown Chickpeas", "brown chickpea", brand="trs", size=1.0)
    assert score(parsed, other, RARITY) < 0.72


def test_damaged_packaging_is_a_separate_listing():
    parsed = parse_title("India Gate Sona Masoori Rice 5kg Damaged Packing")
    other = product(
        "India Gate Sona Masoori Rice 5kg", "sona masoori rice",
        brand="india gate", size=5.0,
    )
    assert score(parsed, other, RARITY) < 0.72


def test_terse_and_verbose_titles_for_the_same_bag_merge():
    """Real split from the live catalogue: the same 10 kg Aashirvaad atta was
    listed five different ways and became five separate products."""
    rarity = {**RARITY, "atta": 3.0, "whole": 1.2, "wheat": 2.0, "flour": 1.5}
    terse = parse_title("Aashirvaad Atta 10kg")
    verbose = product(
        "Aashirvaad Whole Wheat Flour Atta 10Kg",
        "whole wheat flour atta", brand="aashirvaad", size=10.0,
    )
    assert score(terse, verbose, rarity) >= 0.72


def test_flour_no_longer_disqualifies_against_atta():
    """"flour" used to sit in the preparation-form group, which hard-rejected
    "Whole Wheat Flour" against "Whole Wheat Atta"."""
    rarity = {**RARITY, "atta": 3.0, "whole": 1.2, "wheat": 2.0, "flour": 1.5}
    parsed = parse_title("Aashirvaad Whole Wheat Flour (Atta) 10Kg")
    other = product(
        "Aashirvaad Whole Wheat Atta 10kg", "whole wheat atta",
        brand="aashirvaad", size=10.0,
    )
    assert score(parsed, other, rarity) > 0.0


def test_multigrain_atta_is_not_plain_atta():
    rarity = {**RARITY, "atta": 3.0, "multigrain": 4.0}
    parsed = parse_title("Aashirvaad Multigrain Atta 2kg")
    other = product(
        "Aashirvaad Atta 2kg", "atta", brand="aashirvaad", size=2.0
    )
    assert score(parsed, other, rarity) < 0.72


def test_containment_needs_brand_and_size_to_agree():
    """Without those anchors, containment would swallow generic names."""
    rarity = {**RARITY, "rice": 0.8, "basmati": 3.0}
    parsed = parse_title("Rice 1kg")
    other = product("Daawat Basmati Rice 1kg", "basmati rice", brand="daawat", size=1.0)
    assert score(parsed, other, rarity) < 0.72


def test_sauce_flavour_variants_do_not_merge():
    """Same brand, same size, same base product — different thing in the bottle."""
    parsed = parse_title("Flying Goose Sriracha Mayo Chilli Sauce 200ml")
    other = product(
        "Flying Goose Sriracha Satay Sauce 200ml",
        "sriracha satay sauce chilli", brand="flying goose",
        size=0.2, unit="l",
    )
    assert score(parsed, other, RARITY) == 0.0


def test_brand_mismatch_is_disqualifying():
    parsed = parse_title("Heera Cumin Seeds 100g")
    other = product("TRS Cumin Seeds", "cumin seed", brand="trs")
    assert score(parsed, other, RARITY) == 0.0


def test_size_mismatch_is_disqualifying():
    parsed = parse_title("Daawat Basmati Rice 1kg")
    other = product("Daawat Basmati Rice 5kg", "basmati rice", brand="daawat", size=5.0)
    assert score(parsed, other, RARITY) == 0.0


def test_weighted_jaccard_discounts_common_tokens():
    common_only = weighted_jaccard({"coriander", "seed"}, {"sesame", "seed"}, RARITY)
    distinctive = weighted_jaccard({"coriander", "seed"}, {"coriander", "seed"}, RARITY)
    assert common_only < 0.2
    assert distinctive == 1.0


def test_non_product_listings_are_filtered():
    assert is_product("Heera Toor Dal 1kg")
    assert not is_product("Delivery Free GLS pick-up locations")
    assert not is_product("Gift Card 100 PLN")
    assert not is_product("Dostawa kurierska")


def test_descriptive_words_are_not_treated_as_brands():
    assert not _plausible("fresh")
    assert not _plausible("organic")
    assert _plausible("haldiram")


def test_compound_head_nouns_are_not_learned_as_brands(session):
    """Enough titles start with "Garam Masala ..." that leading-token frequency
    alone classifies "garam" as a brand. That demotes the real brand to an
    ordinary token and splits the product across shops."""
    shop = make_shop(session, "alpha")
    titles = [
        "Garam Masala TRS 100g", "Garam Masala Heera 100g",
        "Garam Masala Everest 50g", "Garam Masala MDH 200g",
        "Garam Masala Shan 100g", "Garam Masala Suhana 100g",
        # A real brand: followed by a different product each time.
        "Heera Toor Dal 1kg", "Heera Cumin Seeds 100g",
        "Heera Sago Medium 500g", "Heera Chana Dal 2kg",
    ]
    for i, title in enumerate(titles):
        session.add(
            Offer(
                shop_id=shop.id, external_id=str(i), title=title,
                url="http://x", price=1.0, currency="PLN", price_pln=1.0, raw={},
            )
        )
    session.commit()

    learned = learn_brands(session)
    assert "garam" not in learned
    assert "heera" in learned


def test_polish_product_phrase_is_not_learned_as_a_brand(session):
    """"Mąka pszenna" is Polish for wheat flour. Learned as a brand it gave every
    flour listing the same fake maker, so Schani atta and Aashirvaad atta looked
    like the same brand and merged — a 44.39 zł bag shown as a 78.00 zł one."""
    shop = make_shop(session, "alpha")
    titles = [
        "Mąka pszenna razowa Aashirvaad Atta 10 kg",
        "Mąka pszenna razowa Chapati Atta Schani 10 kg",
        "Mąka pszenna Schani 5 kg",
        "Mąka pszenna razowa Heera 1 kg",
        "Mąka pszenna typ 500 Aashirvaad 2 kg",
        # Four Schani-led titles: the learner needs MIN_TITLES before it will
        # accept a candidate from a single shop.
        "Schani Chapati Atta 5 kg",
        "Schani Basmati Rice 1 kg",
        "Schani Toor Dal 500 g",
        "Schani Cumin Seeds 100 g",
    ]
    for i, title in enumerate(titles):
        session.add(
            Offer(
                shop_id=shop.id, external_id=str(i), title=title,
                url="http://x", price=1.0, currency="PLN", price_pln=1.0, raw={},
            )
        )
    session.commit()

    vocab = learn_brands(session)
    assert "maka pszenna" not in vocab
    assert "schani" in vocab

    schani = parse_title("Mąka pszenna razowa Chapati Atta Schani 10 kg", None, vocab)
    aashirvaad = parse_title("Mąka pszenna razowa Aashirvaad Atta 10 kg", None, vocab)
    assert schani.brand == "schani"
    assert aashirvaad.brand == "aashirvaad"


def test_different_brands_of_the_same_flour_never_merge():
    rarity = {**RARITY, "atta": 3.0, "chapati": 4.0, "razowa": 2.0, "flour": 1.5}
    parsed = parse_title("Mąka pszenna razowa Chapati Atta Schani 10 kg")
    parsed.brand = "schani"
    other = product(
        "Aashirvaad Atta 10kg", "flour pszenna razowa atta",
        brand="aashirvaad", size=10.0,
    )
    assert score(parsed, other, rarity) == 0.0


def test_brand_is_found_when_it_trails_the_product_name(session):
    """Some shops write "<product> <brand> <size>". The brand must still win."""
    shop = make_shop(session, "alpha")
    for i, title in enumerate(
        ["Garam Masala TRS 100g", "Chilli Flakes TRS 100g",
         "Cynamon TRS 100g", "Cloves TRS 50g", "Curry Madras TRS 100g"]
    ):
        session.add(
            Offer(
                shop_id=shop.id, external_id=str(i), title=title,
                url="http://x", price=1.0, currency="PLN", price_pln=1.0, raw={},
            )
        )
    session.commit()

    vocab = learn_brands(session)
    parsed = parse_title("Garam Masala TRS 100g", None, vocab)
    assert parsed.brand == "trs"
    assert "trs" not in parsed.tokens


def test_brand_learning_finds_unlisted_brands_and_skips_product_words(session):
    """'Weikfield' is in no curated list but leads many titles, so it must be
    learned; 'everest tandoori' must not be, because 'everest' stands alone."""
    shop = make_shop(session, "alpha")
    titles = [
        "Weikfield Corn Flour 200g", "Weikfield Custard Powder 100g",
        "Weikfield Baking Powder 50g", "Weikfield Jelly Crystals 90g",
        "Everest Tandoori Chicken Masala 100g", "Everest Chhole Masala 100g",
        "Everest Chaat Masala 100g", "Everest Garam Masala 100g",
    ]
    for i, title in enumerate(titles):
        session.add(
            Offer(
                shop_id=shop.id, external_id=str(i), title=title,
                url="http://x", price=1.0, currency="PLN", price_pln=1.0, raw={},
            )
        )
    session.commit()

    learned = learn_brands(session)
    assert "weikfield" in learned
    assert "everest" in learned
    assert "everest tandoori" not in learned


def test_unknown_words_block_containment():
    """"Select Sharbati" is a premium line, not a description. Containment saw
    only that {atta} fits inside {select, sharbati, atta} and merged a 77.99 zł
    bag with a 99.99 zł one."""
    rarity = {**RARITY, "atta": 3.0, "select": 5.0, "sharbati": 8.0}
    parsed = parse_title("Aashirvaad Atta 10kg")
    other = product(
        "Aashirvaad Select Sharbati Atta 10kg", "select sharbati atta",
        brand="aashirvaad", size=10.0,
    )
    assert score(parsed, other, rarity) < 0.72


def test_known_descriptors_still_allow_containment():
    """The same rule must not undo the flour fix: whole/wheat/flour are all
    vocabulary we define, so they read as description, not variety."""
    rarity = {**RARITY, "atta": 3.0, "whole": 1.2, "wheat": 2.0, "flour": 1.5}
    parsed = parse_title("Aashirvaad Atta 10kg")
    other = product(
        "Aashirvaad Whole Wheat Flour Atta 10kg", "whole wheat flour atta",
        brand="aashirvaad", size=10.0,
    )
    assert score(parsed, other, rarity) >= 0.72
