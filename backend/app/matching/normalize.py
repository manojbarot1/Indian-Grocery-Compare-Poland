"""Turn a messy shop title into structured, comparable facts.

    "DAAWAT Traditional Basmati Reis 1 KG"   ->  brand=daawat
                                                 core="basmati rice traditional"
                                                 size=1.0 kg  base_unit=kg

This is the part that makes or breaks a grocery comparison site. The same tin of
rice is listed in Polish, English and Hindi transliteration across four shops,
with the brand sometimes in the title and sometimes only in the vendor field.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Brands. Order matters only for multi-word brands, which we match first.
# --------------------------------------------------------------------------
BRANDS: set[str] = {
    "daawat", "india gate", "tilda", "kohinoor", "lal qilla", "fortune",
    "heera", "trs", "natco", "east end", "ktc", "rajah", "elephant atta",
    "shan", "mdh", "everest", "mtr", "gits", "catch", "badshah", "eastern",
    "haldiram", "haldirams", "bikano", "balaji", "kurkure", "lays",
    "aashirvaad", "pillsbury", "annapurna", "sujata",
    "amul", "britannia", "parle", "sunfeast", "nestle", "maggi", "knorr",
    "patanjali", "dabur", "himalaya", "vicco", "dettol",
    "nirav", "laxmi", "deep", "swad", "priya", "mother's recipe", "mothers recipe",
    "pran", "ahmed", "national", "mehran", "national foods",
    "chings", "ching's secret", "chings secret", "veeba", "wingreens",
    "nanak", "vadilal", "anmol", "cock brand", "chaokoh", "telephone brand",
    "jivaa", "aarti", "sona", "lotus", "24 mantra", "organic india",
    "bombay kitchen", "gopal", "vimal", "rajdhani", "tata", "tata sampann",
}
MULTIWORD_BRANDS = sorted((b for b in BRANDS if " " in b), key=len, reverse=True)

# --------------------------------------------------------------------------
# Vocabulary normalisation: Polish / English / Hindi transliteration -> one token.
# --------------------------------------------------------------------------
SYNONYMS: dict[str, str] = {
    # staples
    "ryz": "rice", "reis": "rice", "chawal": "rice",
    "maka": "flour", "mehl": "flour", "atta": "atta", "ata": "atta",
    # Polish flour descriptors. Without these, "Mąka pszenna razowa Aashirvaad
    # Atta 10 kg" and "Aashirvaad Whole Wheat Flour (Atta) 10Kg" are the same
    # bag described in two languages and never merge.
    "pszenna": "wheat", "pszenny": "wheat", "pszenne": "wheat", "pszenicy": "wheat",
    "razowa": "whole", "razowy": "whole", "razowe": "whole", "pelnoziarnista": "whole",
    "pelnoziarnisty": "whole", "pelnoziarniste": "whole",
    "aata": "atta", "chakki": "atta",
    "soczewica": "lentil", "lentils": "lentil", "dal": "dal", "daal": "dal",
    "dhal": "dal", "toor": "toor", "tur": "toor", "arhar": "toor",
    "moong": "moong", "mung": "moong", "masoor": "masoor",
    "urad": "urad", "urid": "urad", "chana": "chana", "gram": "chana",
    "ciecierzyca": "chickpea", "chickpeas": "chickpea", "kabuli": "chickpea",
    "fasola": "bean", "beans": "bean", "rajma": "kidneybean",
    "kasza": "semolina", "sooji": "semolina", "suji": "semolina",
    "rawa": "semolina", "besan": "besan",
    "poha": "poha", "papad": "papad", "papadum": "papad", "appalam": "papad",
    "sabudana": "sago", "sago": "sago", "javvarisi": "sago",
    "laddu": "laddu", "ladoo": "laddu", "ladu": "laddu",
    "vermicelli": "vermicelli", "sevai": "vermicelli", "semiya": "vermicelli",
    "murukku": "muruku", "muruku": "muruku", "chakli": "muruku",
    "barbeque": "bbq", "barbecue": "bbq", "bbq": "bbq",
    "khakhara": "khakhra", "khakhra": "khakhra",
    # spices
    "przyprawa": "spice", "przyprawy": "spice", "spices": "spice",
    "kurkuma": "turmeric", "haldi": "turmeric",
    "kolendra": "coriander", "dhania": "coriander",
    "kmin": "cumin", "kminek": "cumin", "jeera": "cumin", "zeera": "cumin",
    "chili": "chilli", "chile": "chilli", "mirch": "chilli",
    "papryczka": "chilli", "papryka": "chilli",
    "czosnek": "garlic", "lehsun": "garlic", "lasan": "garlic",
    "imbir": "ginger", "adrak": "ginger",
    "gorczyca": "mustard", "rai": "mustard", "sarson": "mustard",
    "kozieradka": "fenugreek", "methi": "fenugreek",
    "kardamon": "cardamom", "elaichi": "cardamom", "elachi": "cardamom",
    "gozdziki": "clove", "cloves": "clove", "laung": "clove",
    "cynamon": "cinnamon", "dalchini": "cinnamon",
    "kurkumy": "turmeric", "asafetyda": "asafoetida", "hing": "asafoetida",
    "anyz": "aniseed", "saunf": "fennel", "fennel": "fennel",
    "pieprz": "pepper", "kali": "pepper", "mirchi": "chilli",
    # fats, dairy
    "olej": "oil", "oel": "oil", "tel": "oil",
    "maslo": "butter", "ghi": "ghee", "ghee": "ghee",
    "mleko": "milk", "doodh": "milk", "dahi": "yoghurt", "jogurt": "yoghurt",
    "ser": "cheese", "paneer": "paneer",
    # pantry
    "cukier": "sugar", "chini": "sugar", "jaggery": "jaggery", "gur": "jaggery",
    "sol": "salt", "namak": "salt", "herbata": "tea", "chai": "tea",
    "kawa": "coffee", "miod": "honey", "shahad": "honey",
    "pikle": "pickle", "achar": "pickle", "chutney": "chutney",
    "sos": "sauce", "pasta": "paste", "makaron": "noodle",
    # English plurals. Without these "Atta Noodles" matched no prepared-food
    # rule at all and was filed under Flour & Atta.
    "noodles": "noodle", "noodle": "noodle", "sauces": "sauce",
    "pickles": "pickle", "chutneys": "chutney", "biscuits": "biscuit",
    "cookies": "cookie", "wafers": "wafer", "flakes": "flake",
    "nuts": "nut", "dals": "dal", "breads": "bread", "mixes": "mix",
    "powders": "powder", "oils": "oil", "teas": "tea", "sweets": "sweet",
    "przekaski": "snack", "snacks": "snack", "namkeen": "snack",
    "przekaska": "snack", "orzechy": "nut", "orzech": "nut", "nuts": "nut",
    "peas": "pea", "groch": "pea", "soya": "soybean", "soja": "soybean",
    "ryzowy": "rice", "ryzowa": "rice", "ryzu": "rice", "podi": "spice",
    "bhel": "snack", "zapach": "fragrance", "zapachu": "fragrance",
    "kokosowy": "coconut", "kokos": "coconut", "coconut": "coconut",
    # Japanese / pan-Asian staples, common at the oriental shops
    "sushi": "sushi", "nori": "sushi", "wasabi": "wasabi", "ramen": "noodle",
    "ramenu": "noodle", "udon": "noodle", "soba": "noodle", "miso": "miso",
    "ciastka": "biscuit", "ciasto": "cake", "cake": "cake", "deser": "dessert",
    "lemoniada": "drink", "napoj": "drink", "napoje": "drink", "sok": "juice",
    "dzem": "jam", "jam": "jam", "miod": "honey",
    # meat & fish
    "kurczak": "chicken", "kurczaka": "chicken", "chicken": "chicken",
    "mieso": "meat", "meat": "meat", "baranina": "mutton", "mutton": "mutton",
    "jagniecina": "lamb", "lamb": "lamb", "ryba": "fish", "ryby": "fish",
    "fish": "fish", "krewetki": "prawn", "prawn": "prawn", "halal": "halal",
    # personal care (Polish) — these decide household vs food for "oil"
    "wlosow": "hair", "wlosy": "hair", "ciala": "body", "twarzy": "face",
    "mycia": "wash", "zel": "gel", "krem": "cream", "mydlo": "soap",
    "szampon": "shampoo", "pasta do zebow": "toothpaste", "zebow": "toothpaste",
    "olejek": "careoil", "balsam": "balsam", "farba": "dye", "dye": "dye",
    # health / ayurveda
    "ayurveda": "ayurveda", "ajurwedyjski": "ayurveda", "ajurwedyjska": "ayurveda",
    "chyawanprash": "ayurveda", "ashwagandha": "ayurveda", "triphala": "ayurveda",
    "suplement": "supplement", "supplement": "supplement",
    "tabletki": "tablet", "tablet": "tablet", "kapsulki": "capsule",
    # kitchenware / homeware
    "miska": "bowl", "miseczka": "bowl", "bowl": "bowl", "talerz": "plate",
    "kubek": "mug", "garnek": "pot", "patelnia": "pan", "paleczki": "chopsticks",
    "ceramiczna": "ceramic", "ceramiczny": "ceramic", "zestaw": "set",
    "pokrowiec": "cover", "puszka": "tin", "sito": "sieve", "lyzka": "spoon",
    "noz": "knife", "deska": "board", "czapka": "cap", "koszulka": "shirt",
    # Cookware and small appliances. Without these a rice cooker was filed
    # under the Rice food aisle, because "rice" was the only token that matched.
    "szybkowar": "cooker", "cooker": "cooker", "czajnik": "kettle",
    "mikser": "mixer", "blender": "blender", "termos": "thermos",
    "tawa": "tawa", "kadai": "kadai", "grinder": "grinder",
    "sitko": "strainer", "tarka": "grater", "pojemnik": "container",
    "indukcyjna": "induction", "indukcje": "induction",
    "mrozone": "frozen", "frozen": "frozen", "swieze": "fresh",
    # descriptors worth keeping distinct
    "caly": "whole", "whole": "whole", "mielony": "ground", "ground": "ground",
    "powder": "powder", "proszek": "powder", "pudra": "powder",
    "nasiona": "seed", "seeds": "seed", "lisc": "leaf", "leaves": "leaf",
    "organiczny": "organic", "organic": "organic", "bio": "organic",
    "bezglutenowy": "glutenfree", "ostry": "hot", "lagodny": "mild",
}

# Marketing noise that must not influence matching.
#
# The Polish adjectives matter as much as the English ones. Several shops title
# products as "<name> <size> – <marketing tagline>", e.g.
# "Garam Masala TRS 100g – Aromatyczna Przyprawa Indyjska". Those tagline words
# are rare across the corpus, so idf weighting treats them as highly
# distinctive and they block genuine matches unless stripped here.
STOPWORDS: set[str] = {
    "the", "and", "with", "for", "of", "in", "a", "an", "z", "i", "do", "na",
    "new", "nowy", "premium", "best", "quality", "authentic", "original",
    "indian", "indyjski", "indyjska", "indyjskie", "pack", "packet", "opakowanie",
    "product", "produkt", "brand", "marka", "buy", "online", "sklep", "offer",
    "fresh", "imported", "traditional",
    # Polish marketing adjectives and connectives
    "aromatyczna", "aromatyczny", "aromatyczne", "aromatic",
    "naturalna", "naturalny", "naturalne", "natural",
    "intensywna", "intensywny", "intensywne", "intense",
    "tradycyjna", "tradycyjny", "tradycyjne",
    "specjalna", "specjalny", "specjalne", "special",
    "oryginalna", "oryginalny", "oryginalne",
    "wyjatkowa", "wyjatkowy", "wyjatkowe", "doskonala", "doskonaly", "doskonale",
    "najlepsza", "najlepszy", "najlepsze", "idealna", "idealny", "idealne",
    "prawdziwa", "prawdziwy", "prawdziwe", "klasyczna", "klasyczny", "klasyczne",
    "wysokiej", "jakosci", "spozywczy", "spozywcze", "spozywcza", "smak", "smaku", "smakiem", "potraw", "potrawy",
    "kuchni", "kuchnia", "orientalna", "orientalny", "orientalne",
    "azjatycka", "azjatycki", "azjatyckie", "asian",
}

# Words that define a product variant rather than describe it. Two offers that
# disagree inside any one of these groups are different products, however
# similar the rest of the title reads: "Madras Curry Powder Mild" is not
# "Madras Curry Powder Hot", and "Chickpeas" is not "Brown Chickpeas".
#
# These tokens are common, so idf-weighted overlap alone barely notices them —
# they have to be checked explicitly.
#
# HARD groups are decisive even when the word appears on only one side:
# "Multigrain Atta" is not "Atta", full stop.
HARD_DISCRIMINATOR_GROUPS: list[set[str]] = [
    {"hot", "mild", "medium", "extrahot"},
    {"white", "brown", "red", "green", "black", "yellow", "pink", "blue"},
    # Condition/grade: a damaged-packaging or broken-grain listing is a cheaper
    # different product, and must never set the headline price for the good one.
    {"damaged", "broken", "cracked"},
    # Variety is decisive: multigrain atta is not plain atta.
    {"multigrain", "multigrains", "buckwheat", "ragi", "bajra", "jowar"},
    {"sweet", "salted", "unsalted", "sour", "plain", "spicy"},
    {"raw", "roasted", "fried", "boiled", "steamed"},
    {"organic", "regular"},
    {"frozen", "fresh", "dried", "canned"},
    # Flavour variants of the same sauce or snack line. Without this,
    # "Flying Goose Sriracha Mayo" merges with "Flying Goose Sriracha Satay"
    # — same brand, same size, same base product, different thing in the bottle.
    {"mayo", "mayonnaise", "satay", "teriyaki", "hoisin", "oyster", "ketchup",
     "curry", "peri", "wasabi", "sesame", "honey"},
]

# SOFT groups matter only when both sides name a value and the values differ:
# "Cumin Whole" is not "Cumin Powder". But one side saying nothing is normal
# shop shorthand — "Aashirvaad Atta" and "Aashirvaad Whole Wheat Atta" are the
# same 10 kg bag, so a one-sided "whole" must not split them.
#
# "flour", "oil", "paste" and "leaf" were in this group once and it was wrong:
# they are product nouns, not points on the preparation axis, and having them
# here hard-rejected "Whole Wheat Flour (Atta)" against "Whole Wheat Atta".
SOFT_DISCRIMINATOR_GROUPS: list[set[str]] = [
    {"whole", "ground", "powder", "seed", "crushed", "flake"},
]

# Back-compat alias: every group, for callers that only need "is this decisive".
DISCRIMINATOR_GROUPS = HARD_DISCRIMINATOR_GROUPS + SOFT_DISCRIMINATOR_GROUPS

UNIT_ALIASES: dict[str, tuple[str, float]] = {
    # alias -> (base_unit, multiplier to base)
    "kg": ("kg", 1.0), "kilo": ("kg", 1.0), "kilogram": ("kg", 1.0),
    "g": ("kg", 0.001), "gr": ("kg", 0.001), "gm": ("kg", 0.001),
    "gram": ("kg", 0.001), "grams": ("kg", 0.001), "gramow": ("kg", 0.001),
    "mg": ("kg", 1e-6),
    "l": ("l", 1.0), "ltr": ("l", 1.0), "litr": ("l", 1.0), "litre": ("l", 1.0),
    "liter": ("l", 1.0),
    "ml": ("l", 0.001), "cl": ("l", 0.01),
    "pc": ("pc", 1.0), "pcs": ("pc", 1.0), "piece": ("pc", 1.0),
    "pieces": ("pc", 1.0), "szt": ("pc", 1.0), "sztuk": ("pc", 1.0),
}

_UNIT_RE = "|".join(sorted(UNIT_ALIASES, key=len, reverse=True))
# "6 x 500g", "6x500 g"
MULTIPACK_RE = re.compile(
    rf"(?<![\w.])(\d{{1,3}})\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*({_UNIT_RE})(?![a-z])",
    re.IGNORECASE,
)
# The same thing written the other way round: "5kg X3", "500g x 6".
SUFFIX_MULTIPACK_RE = re.compile(
    rf"(?<![\w.])(\d+(?:[.,]\d+)?)\s*({_UNIT_RE})\s*[x×]\s*(\d{{1,3}})(?![\w.])",
    re.IGNORECASE,
)
# "Pack of 3", "Bundle of 2", "Combo of 4"
PACK_OF_RE = re.compile(
    r"\b(?:pack|bundle|combo|set|zestaw)\s+(?:of\s+)?(\d{1,3})\b", re.IGNORECASE
)
# "1kg", "500 g", "1,5 l"
SIZE_RE = re.compile(
    rf"(?<![\w.])(\d+(?:[.,]\d+)?)\s*({_UNIT_RE})(?![a-z])", re.IGNORECASE
)


CANONICAL_TOKENS: set[str] = set(SYNONYMS.values())
"""Every token our vocabulary can explain — the canonical side of SYNONYMS.

Used to tell a *description* from a *variety*. "Whole wheat flour atta" adds
only words we understand, so it is the same bag as "atta". "Select Sharbati
atta" adds words we have never defined, and those are exactly where product
lines hide.
"""


def strip_accents(text: str) -> str:
    """Fold Polish diacritics so 'mąka' and 'maka' are the same token."""
    text = text.replace("ł", "l").replace("Ł", "L")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def basic_clean(text: str) -> str:
    text = strip_accents(text or "").lower()
    text = re.sub(r"&[a-z]+;", " ", text)          # stray HTML entities
    text = re.sub(r"[^a-z0-9.,×x\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class ParsedSize:
    value: float | None = None          # quantity in the original unit
    unit: str | None = None             # the unit as written, e.g. "g"
    base_unit: str | None = None        # kg | l | pc
    base_value: float | None = None     # quantity converted to base_unit
    multipack: int = 1


def _multipack(value: float, unit: str, count: int) -> ParsedSize:
    base_unit, mult = UNIT_ALIASES[unit.lower()]
    return ParsedSize(
        value=value, unit=unit.lower(), base_unit=base_unit,
        base_value=round(value * mult * count, 6), multipack=count,
    )


def parse_size(text: str) -> ParsedSize:
    """Extract pack size. Multipacks win over single sizes: '6 x 500g' is 3 kg.

    A combo must not collapse into the single unit — otherwise a "5kg X3" listing
    at triple the price becomes the headline price for the plain 5 kg bag.
    """
    cleaned = strip_accents(text or "").lower()

    m = MULTIPACK_RE.search(cleaned)
    if m:
        return _multipack(float(m.group(2).replace(",", ".")), m.group(3), int(m.group(1)))

    m = SUFFIX_MULTIPACK_RE.search(cleaned)
    if m:
        return _multipack(float(m.group(1).replace(",", ".")), m.group(2), int(m.group(3)))

    matches = SIZE_RE.findall(cleaned)

    # "Rice 5kg, pack of 3" — the count sits apart from the size.
    pack = PACK_OF_RE.search(cleaned)
    if pack and matches:
        count = int(pack.group(1))
        if count > 1:
            largest = max(
                matches, key=lambda pair: float(pair[0].replace(",", "."))
                * UNIT_ALIASES[pair[1].lower()][1]
            )
            return _multipack(
                float(largest[0].replace(",", ".")), largest[1], count
            )

    if not matches:
        return ParsedSize()
    # Prefer the largest match: "Rice 1kg (net 950g)" should read as 1kg.
    best = None
    for raw_value, raw_unit in matches:
        value = float(raw_value.replace(",", "."))
        base_unit, mult = UNIT_ALIASES[raw_unit.lower()]
        base_value = value * mult
        if best is None or base_value > best.base_value:
            best = ParsedSize(
                value=value, unit=raw_unit.lower(), base_unit=base_unit,
                base_value=round(base_value, 6),
            )
    return best or ParsedSize()


def extract_brand(
    text: str, vendor: str | None = None, vocab: set[str] | None = None
) -> str | None:
    """Brand from the title if present, else from the shop's vendor field —
    but only when the vendor is a real brand and not the shop's own name.

    `vocab` overrides the curated seed list; brands.learn_brands() builds a much
    larger one from the catalogue itself.
    """
    vocab = vocab if vocab is not None else BRANDS
    multiword = sorted((b for b in vocab if " " in b), key=len, reverse=True)

    cleaned = basic_clean(text)
    for brand in multiword:
        if re.search(rf"\b{re.escape(brand)}\b", cleaned):
            return brand
    for token in cleaned.split():
        if token in vocab:
            return token
    if vendor:
        v = basic_clean(vendor)
        if v in vocab:
            return v
        for brand in multiword:
            if brand in v:
                return brand
    return None


def canonical_tokens(text: str, brand: str | None = None) -> list[str]:
    """Words that actually identify the product: no brand, no size, no noise,
    every synonym folded to one canonical token."""
    cleaned = basic_clean(text)

    if brand:
        cleaned = re.sub(rf"\b{re.escape(brand)}\b", " ", cleaned)
    cleaned = MULTIPACK_RE.sub(" ", cleaned)
    cleaned = SUFFIX_MULTIPACK_RE.sub(" ", cleaned)
    cleaned = SIZE_RE.sub(" ", cleaned)

    tokens: list[str] = []
    for token in cleaned.split():
        token = token.strip("-.,")
        if not token or token in STOPWORDS:
            continue
        # A bare number left over after size removal carries no meaning.
        if token.replace(".", "").replace(",", "").isdigit():
            continue
        token = SYNONYMS.get(token, token)
        if token in STOPWORDS or len(token) < 2:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


@dataclass
class ParsedTitle:
    raw: str
    brand: str | None
    tokens: list[str] = field(default_factory=list)
    size: ParsedSize = field(default_factory=ParsedSize)

    @property
    def core(self) -> str:
        return " ".join(sorted(self.tokens))

    @property
    def match_key(self) -> str:
        """Blocking key. Two offers are only ever compared if this matches, so
        it must be cheap, stable, and never split a genuine pair.

        Size is deliberately part of the key: 500 g and 1 kg of the same rice
        are different products with different prices, not one product.
        """
        brand = self.brand or "_"
        size = (
            f"{self.size.base_value:g}{self.size.base_unit}"
            if self.size.base_value and self.size.base_unit
            else "_"
        )
        anchor = "-".join(sorted(self.tokens)[:3]) or "_"
        return f"{brand}|{anchor}|{size}"


def parse_title(
    title: str, vendor: str | None = None, vocab: set[str] | None = None
) -> ParsedTitle:
    brand = extract_brand(title, vendor, vocab)
    return ParsedTitle(
        raw=title,
        brand=brand,
        tokens=canonical_tokens(title, brand),
        size=parse_size(title),
    )


def resolve_size(parsed: ParsedTitle, weight_grams: int | None) -> ParsedSize:
    """Best available pack size: the title if it states one, else the shop's
    declared parcel weight.

    Title first, deliberately. A shop's weight is the shipping weight and
    includes packaging, so a "1 kg" bag often ships as 1050 g — fine for
    shipping bands, wrong for price-per-kg.
    """
    if parsed.size.base_value:
        return parsed.size
    if weight_grams:
        return parse_size(f"{weight_grams}g")
    return parsed.size


def apply_size(offer, parsed: ParsedTitle) -> None:
    """Write the normalised size and unit price onto an Offer. Shared by ingest
    and matching so the two can never disagree."""
    size = resolve_size(parsed, offer.weight_grams)
    offer.size_value = size.base_value
    offer.size_unit = size.unit
    offer.base_unit = size.base_unit
    offer.unit_price_pln = unit_price(offer.price_pln, size)


def unit_price(price: float, size: ParsedSize) -> float | None:
    """Price per kg / litre / piece — the number that actually compares two
    grocery offers. Returns None when the pack size is unknown."""
    if not size.base_value or size.base_value <= 0 or not size.base_unit:
        return None
    return round(price / size.base_value, 4)
