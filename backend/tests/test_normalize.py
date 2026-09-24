from __future__ import annotations

import pytest

from app.matching.normalize import parse_size, parse_title, unit_price


@pytest.mark.parametrize(
    "title,expected_base,expected_unit",
    [
        ("Daawat Basmati Rice 1kg", 1.0, "kg"),
        ("Heera Cumin Seeds 100g", 0.1, "kg"),
        ("MDH Garam Masala 500 g", 0.5, "kg"),
        ("Amul Ghee 1 L", 1.0, "l"),
        ("Coconut Milk 400ml", 0.4, "l"),
        ("Tilda Basmati 5 KG", 5.0, "kg"),
        ("Maggi Noodles 72.5g", 0.0725, "kg"),
        ("Mango Pickle 1,5 kg", 1.5, "kg"),
    ],
)
def test_parse_size(title, expected_base, expected_unit):
    size = parse_size(title)
    assert size.base_unit == expected_unit
    assert size.base_value == pytest.approx(expected_base)


def test_multipack_beats_single_size():
    size = parse_size("Maggi Masala Noodles 6 x 70g")
    assert size.multipack == 6
    assert size.base_value == pytest.approx(0.42)


def test_suffix_multipack_is_not_read_as_a_single_pack():
    """A real listing: 'India Gate Sona Masoori Rice 5kg X3 COMBO' costs triple
    the single bag, so reading it as 5 kg would poison that product's price."""
    size = parse_size("India Gate Sona Masoori Rice 5kg X3 COMBO")
    assert size.multipack == 3
    assert size.base_value == pytest.approx(15.0)


def test_pack_of_n_is_applied_to_the_size():
    size = parse_size("Heera Toor Dal 1kg, Pack of 4")
    assert size.multipack == 4
    assert size.base_value == pytest.approx(4.0)


def test_combo_does_not_share_a_key_with_the_single_unit():
    single = parse_title("India Gate Sona Masoori Rice 5kg")
    combo = parse_title("India Gate Sona Masoori Rice 5kg X3 COMBO")
    assert single.match_key != combo.match_key


def test_polish_diacritics_and_synonyms_fold_together():
    pl = parse_title("Mąka pszenna Aashirvaad 1kg")
    en = parse_title("Aashirvaad Wheat Flour 1 kg")
    assert pl.brand == en.brand == "aashirvaad"
    assert "flour" in pl.tokens and "flour" in en.tokens
    assert pl.size.base_value == en.size.base_value == 1.0


def test_hindi_transliteration_folds_to_english():
    assert "turmeric" in parse_title("Haldi Powder 200g").tokens
    assert "cumin" in parse_title("Jeera Whole 100g").tokens
    assert "coriander" in parse_title("Dhania Powder 100g").tokens


def test_brand_is_stripped_from_core_tokens():
    parsed = parse_title("TRS Chana Dal 1kg")
    assert parsed.brand == "trs"
    assert "trs" not in parsed.tokens


def test_marketing_noise_is_ignored():
    a = parse_title("Heera Toor Dal 1kg")
    b = parse_title("Heera Premium Quality Authentic Indian Toor Dal 1kg")
    assert a.match_key == b.match_key


def test_polish_marketing_tagline_is_stripped():
    """Real listing style: '<name> <size> – <tagline>'. The tagline words are
    rare, so leaving them in blocks the match against a plain title."""
    tagline = parse_title("Garam Masala TRS 100g – Aromatyczna Przyprawa Indyjska")
    assert tagline.brand == "trs"
    assert tagline.size.base_value == pytest.approx(0.1)
    # The marketing adjectives are gone; only the product words survive.
    assert "aromatyczna" not in tagline.tokens
    assert "indyjska" not in tagline.tokens
    assert {"garam", "masala"} <= set(tagline.tokens)


def test_brand_is_found_even_when_it_is_not_the_first_word():
    parsed = parse_title("Curry Madras Łagodne TRS 100g")
    assert parsed.brand == "trs"
    assert parsed.size.base_value == pytest.approx(0.1)


def test_different_sizes_never_share_a_match_key():
    small = parse_title("Daawat Basmati Rice 1kg")
    large = parse_title("Daawat Basmati Rice 5kg")
    assert small.match_key != large.match_key


def test_unit_price_normalises_pack_size():
    size = parse_size("Rice 5kg")
    assert unit_price(50.0, size) == pytest.approx(10.0)


def test_unit_price_is_none_without_a_size():
    assert unit_price(12.0, parse_size("Brass Kalash")) is None
