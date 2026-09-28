"""Assign each canonical product to a shopping category.

Shop-supplied categories are useless for this: every shop names them
differently ("MĄKA", "Flour, Grain & Pulses", "Kasze i zboża"), many shops
supply none at all, and the HTML-scraped shops have no category data whatsoever.

Instead we derive the category from the canonical tokens the matcher already
produces, which are language-normalised — so a Polish "mąka" listing and an
English "atta" listing land in the same aisle without any per-shop mapping.
"""

from __future__ import annotations

# Priority decides ties, and ties are common: "Maggi Atta Noodles" hits both
# atta-flour and ready-meals with one token each. What a product *is* beats what
# it is *made of* — it is a noodle, not flour — so prepared foods outrank the
# ingredient they are made from.
# Tiers, lowest to highest. A higher tier wins a tie on token count.
#   INGREDIENT — what a thing is made of ("atta", "rice")
#   PREPARED   — what it has been made into ("noodle", "pickle")
#   STRONG     — head nouns that admit no argument ("tea", "milk", "chicken");
#                "BRU Instant Coffee" is a drink, not a mix
#   NONFOOD    — not groceries at all; a ceramic "sauce bowl" is kitchenware
INGREDIENT, PREPARED, STRONG, NONFOOD = 1, 2, 3, 4

# (slug, label, trigger tokens, priority)
CATEGORY_RULES: list[tuple[str, str, set[str], int]] = [
    (
        "rice",
        "Rice",
        {
            "rice", "basmati", "sella", "kolam", "sona", "masoori", "poha",
            "jasmine", "matta", "ponni", "idli",
        },
        INGREDIENT,
    ),
    (
        "atta-flour",
        "Flour & Atta",
        {
            "atta", "flour", "besan", "semolina", "maida", "ragi", "bajra",
            "jowar", "cornflour", "arrowroot",
        },
        INGREDIENT,
    ),
    (
        "dal-pulses",
        "Dal & Pulses",
        {
            "dal", "lentil", "chana", "moong", "masoor", "urad", "toor",
            "chickpea", "bean", "kidneybean", "pea", "rajma", "lobia",
            "soybean", "peanut", "groundnut", "pea",
        },
        INGREDIENT,
    ),
    (
        "spices",
        "Spices & Masala",
        {
            "spice", "masala", "turmeric", "cumin", "coriander", "chilli",
            "cardamom", "clove", "cinnamon", "fenugreek", "mustard",
            "asafoetida", "pepper", "fennel", "aniseed", "bay", "nutmeg",
            "saffron", "garam", "tandoori", "biryani", "curry", "ajwain",
            "kalonji", "amchur", "anardana", "mace", "tamarind",
        },
        INGREDIENT,
    ),
    ("oil-ghee", "Oil & Ghee", {"oil", "ghee", "vanaspati"}, INGREDIENT),
    (
        "sweeteners",
        "Sugar & Sweeteners",
        {"sugar", "jaggery", "honey", "syrup", "salt"},
        INGREDIENT,
    ),
    (
        "fresh",
        "Fresh Produce",
        {
            "vegetable", "fruit", "okra", "gourd", "ginger", "garlic", "onion",
            "potato", "tomato", "curryleaf", "brinjal", "spinach", "chilli",
            "coconut",
        },
        INGREDIENT,
    ),
    (
        "pickle-sauce",
        "Pickles & Sauces",
        {
            "pickle", "chutney", "sauce", "paste", "vinegar", "ketchup",
            "mayo", "soy", "relish", "dip",
        },
        PREPARED,
    ),
    (
        "snacks",
        "Snacks & Sweets",
        {
            "snack", "biscuit", "cookie", "muruku", "laddu", "papad", "chikki",
            "namkeen", "wafer", "chips", "rusk", "khakhra", "barfi", "halwa",
            "sweet", "candy", "chocolate", "bhujia", "sev", "mixture",
            "kachori", "samosa", "pakora", "mathri", "gathiya", "farsan",
            "popcorn", "cracker", "gulab", "jamun", "rasgulla", "soan",
            "nut", "cashew", "almond", "raisin", "pista", "dessert", "cake", "jam",
        },
        PREPARED,
    ),
    (
        "ready-meals",
        "Ready Meals & Mixes",
        {
            "mix", "ready", "instant", "noodle", "vermicelli", "pasta", "soup",
            "dosa", "upma", "paratha", "roti", "naan", "chapati", "bread",
            "batter", "tempura", "curryready", "sushi", "miso", "wasabi",
        },
        PREPARED,
    ),
    (
        "dairy-frozen",
        "Dairy & Frozen",
        {"milk", "paneer", "yoghurt", "cheese", "frozen", "ice", "butter"},
        STRONG,
    ),
    (
        "drinks",
        "Drinks & Tea",
        {
            "tea", "coffee", "juice", "drink", "water", "squash", "sharbat",
            "lassi", "soda", "cola", "beverage", "juice",
        },
        STRONG,
    ),
    (
        "household",
        "Home & Personal Care",
        {
            "soap", "shampoo", "toothpaste", "detergent", "incense", "agarbatti",
            "hair", "skin", "puja", "diya", "utensil", "copper", "wick",
            "camphor", "cosmetic", "lotion", "henna", "mehndi",
            "careoil", "balsam", "dye", "face", "wash", "gel", "body",
            "fragrance", "perfume",
        },
        NONFOOD,
    ),
    (
        "kitchenware",
        "Kitchen & Home",
        {
            "bowl", "plate", "mug", "pot", "pan", "chopsticks", "ceramic",
            "spoon", "knife", "board", "sieve", "tin", "cover", "set",
            "cap", "shirt", "kalash", "lamp",
            # Cookware and small appliances — a rice cooker is a cooker, not rice.
            "cooker", "pressure", "tawa", "kadai", "grinder", "mixer",
            "blender", "kettle", "thermos", "tiffin", "casserole",
            "strainer", "grater", "scraper", "flask", "container", "induction",
        },
        NONFOOD,
    ),
    (
        "health",
        "Health & Ayurveda",
        {"ayurveda", "supplement", "tablet", "capsule", "antacid", "herbal"},
        NONFOOD,
    ),
    (
        "meat-fish",
        "Meat & Fish",
        {"chicken", "meat", "mutton", "lamb", "fish", "prawn", "halal"},
        STRONG,
    ),
]

FALLBACK = ("other", "Other")

# Tokens decisive enough to win outright. "Coconut Oil" belongs in Oil & Ghee
# but "Hair Oil" does not, and a token like "oil" cannot tell them apart.
HOUSEHOLD_OVERRIDES = {
    "shampoo", "soap", "toothpaste", "detergent", "incense", "agarbatti",
    "diya", "camphor", "wick", "utensil", "copper", "puja", "henna", "mehndi",
    "lotion", "cosmetic",
}


def categorise(tokens: list[str]) -> tuple[str, str]:
    """Return (slug, label) for a product's canonical tokens."""
    token_set = set(tokens)

    if token_set & HOUSEHOLD_OVERRIDES:
        return "household", "Home & Personal Care"

    best: tuple[str, str] | None = None
    best_key = (0, 0)
    for slug, label, triggers, priority in CATEGORY_RULES:
        hits = len(token_set & triggers)
        if not hits:
            continue
        # More matching tokens wins; a tie goes to the higher priority, so a
        # prepared food beats the ingredient it is made from.
        key = (hits, priority)
        if key > best_key:
            best_key, best = key, (slug, label)
    return best or FALLBACK


LABELS: dict[str, str] = {slug: label for slug, label, _, _ in CATEGORY_RULES}
LABELS[FALLBACK[0]] = FALLBACK[1]


# --------------------------------------------------------------------------
# Sub-categories
# --------------------------------------------------------------------------
# One level down, scoped to a parent. 201 products in "Flour & Atta" is a list,
# not a filter — wheat atta, besan and semolina are different shopping
# decisions. Same rules as the parent taxonomy: most matching tokens wins, and
# anything that matches nothing keeps the parent only.
SUBCATEGORY_RULES: dict[str, list[tuple[str, str, set[str]]]] = {
    "atta-flour": [
        ("wheat-atta", "Wheat Atta", {"atta", "wheat", "chapati"}),
        ("besan", "Besan / Gram Flour", {"besan", "chickpea", "chana"}),
        ("semolina", "Semolina / Sooji", {"semolina"}),
        ("maida", "Maida / Plain Flour", {"maida"}),
        ("rice-flour", "Rice Flour", {"rice"}),
        ("corn-flour", "Corn Flour", {"cornflour", "corn", "maize"}),
        ("millet-flour", "Millet Flour", {"ragi", "bajra", "jowar", "millet", "sorghum"}),
    ],
    "rice": [
        ("basmati", "Basmati", {"basmati"}),
        ("sona-masoori", "Sona Masoori / Ponni", {"sona", "masoori", "ponni", "matta"}),
        ("idli-rice", "Idli / Parboiled", {"idli", "parboiled"}),
        ("jasmine", "Jasmine", {"jasmine"}),
        ("poha", "Poha / Flattened", {"poha"}),
    ],
    "dal-pulses": [
        ("toor", "Toor Dal", {"toor"}),
        ("moong", "Moong Dal", {"moong"}),
        ("chana", "Chana Dal", {"chana", "chickpea"}),
        ("masoor", "Masoor / Lentils", {"masoor", "lentil"}),
        ("urad", "Urad Dal", {"urad"}),
        ("beans", "Beans", {"bean", "rajma", "kidneybean", "lobia", "soybean"}),
        ("peanuts", "Peanuts", {"peanut", "groundnut"}),
        ("peas", "Peas", {"pea"}),
    ],
    "spices": [
        ("blends", "Masala Blends", {"masala", "garam", "biryani", "tandoori", "curry"}),
        ("chilli", "Chilli", {"chilli"}),
        ("turmeric", "Turmeric", {"turmeric"}),
        ("cumin-coriander", "Cumin & Coriander", {"cumin", "coriander"}),
        ("whole-spices", "Whole Spices", {"cardamom", "clove", "cinnamon", "bay", "nutmeg", "mace"}),
        ("seeds", "Seeds", {"seed", "mustard", "fenugreek", "fennel", "ajwain", "kalonji"}),
    ],
    "pickle-sauce": [
        ("pickle", "Pickles", {"pickle"}),
        ("chutney", "Chutney", {"chutney"}),
        ("cooking-paste", "Cooking Pastes", {"paste"}),
        ("sauce", "Sauces", {"sauce", "ketchup", "soy", "mayo", "dip"}),
        ("vinegar", "Vinegar", {"vinegar"}),
    ],
    "snacks": [
        ("namkeen", "Namkeen", {"namkeen", "bhujia", "sev", "mixture", "gathiya", "farsan", "snack"}),
        ("biscuits", "Biscuits", {"biscuit", "cookie", "rusk", "cracker"}),
        ("chips", "Chips & Wafers", {"chips", "wafer", "popcorn"}),
        ("sweets", "Indian Sweets", {"sweet", "barfi", "laddu", "halwa", "jamun", "gulab", "rasgulla", "soan", "dessert"}),
        ("chocolate", "Chocolate & Candy", {"chocolate", "candy"}),
        ("papad", "Papad & Khakhra", {"papad", "khakhra"}),
        ("nuts", "Nuts & Dry Fruit", {"nut", "cashew", "almond", "raisin", "pista"}),
    ],
    "ready-meals": [
        ("noodles", "Noodles & Pasta", {"noodle", "vermicelli", "pasta"}),
        ("ready-to-eat", "Ready to Eat", {"ready", "curryready"}),
        ("mixes", "Cooking Mixes", {"mix", "batter", "dosa", "upma", "idli"}),
        ("breads", "Breads & Parathas", {"paratha", "roti", "naan", "chapati", "bread"}),
        ("soup", "Soups", {"soup"}),
        ("sushi", "Sushi & Japanese", {"sushi", "miso", "wasabi"}),
    ],
    "drinks": [
        ("tea", "Tea", {"tea"}),
        ("coffee", "Coffee", {"coffee"}),
        ("juice", "Juice & Squash", {"juice", "squash", "sharbat"}),
        ("soft-drinks", "Soft Drinks & Water", {"drink", "soda", "cola", "water"}),
        ("lassi", "Lassi", {"lassi"}),
    ],
    "dairy-frozen": [
        ("paneer", "Paneer", {"paneer"}),
        ("milk", "Milk & Cream", {"milk"}),
        ("yoghurt", "Yoghurt", {"yoghurt"}),
        ("cheese", "Cheese", {"cheese"}),
        ("butter", "Butter", {"butter"}),
        ("frozen", "Frozen", {"frozen", "ice"}),
    ],
    "oil-ghee": [
        ("ghee", "Ghee", {"ghee"}),
        ("cooking-oil", "Cooking Oil", {"oil", "vanaspati"}),
    ],
    "sweeteners": [
        ("sugar", "Sugar", {"sugar"}),
        ("jaggery", "Jaggery", {"jaggery"}),
        ("honey", "Honey", {"honey"}),
        ("salt", "Salt", {"salt"}),
    ],
    "meat-fish": [
        ("chicken", "Chicken", {"chicken"}),
        ("mutton-lamb", "Mutton & Lamb", {"mutton", "lamb"}),
        ("fish-seafood", "Fish & Seafood", {"fish", "prawn"}),
    ],
    "fresh": [
        ("vegetables", "Vegetables", {"vegetable", "okra", "gourd", "potato", "onion", "tomato", "brinjal", "spinach"}),
        ("fruit", "Fruit", {"fruit", "coconut"}),
        ("aromatics", "Ginger, Garlic & Herbs", {"ginger", "garlic", "curryleaf"}),
    ],
    "household": [
        ("hair-care", "Hair Care", {"hair", "shampoo", "careoil", "dye", "henna", "mehndi"}),
        ("skin-care", "Skin Care", {"skin", "face", "cream", "lotion", "soap", "wash", "gel", "body"}),
        ("oral-care", "Oral Care", {"toothpaste"}),
        ("puja", "Puja & Incense", {"incense", "agarbatti", "puja", "diya", "camphor", "wick", "fragrance"}),
        ("cleaning", "Cleaning", {"detergent"}),
    ],
    "kitchenware": [
        ("appliances", "Appliances", {"cooker", "grinder", "mixer", "blender", "kettle"}),
        ("cookware", "Cookware", {"pot", "pan", "tawa", "kadai", "pressure", "casserole", "induction"}),
        ("tableware", "Tableware", {"bowl", "plate", "mug", "ceramic"}),
        ("utensils", "Utensils", {"spoon", "knife", "board", "sieve", "chopsticks", "utensil"}),
        ("storage", "Storage", {"tin", "cover", "set", "container", "flask", "thermos", "tiffin"}),
    ],
    "health": [
        ("ayurveda", "Ayurvedic", {"ayurveda", "herbal"}),
        ("supplements", "Supplements", {"supplement", "tablet", "capsule", "antacid"}),
    ],
}

SUB_LABELS: dict[str, str] = {
    slug: label
    for rules in SUBCATEGORY_RULES.values()
    for slug, label, _ in rules
}


def subcategorise(category: str, tokens: list[str]) -> str | None:
    """Sub-category slug within `category`, or None if nothing matches."""
    rules = SUBCATEGORY_RULES.get(category)
    if not rules:
        return None

    token_set = set(tokens)
    best: str | None = None
    best_hits = 0
    for slug, _label, triggers in rules:
        hits = len(token_set & triggers)
        if hits > best_hits:
            best_hits, best = hits, slug
    return best
