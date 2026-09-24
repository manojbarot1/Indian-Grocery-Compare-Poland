"""Tests for the generic sitemap+HTML adapter, written from the bugs the live
indiancorner.pl catalogue produced."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.ingest.html_shop import HtmlShopAdapter, parse_price

from .conftest import make_shop


def adapter(session, **ingest):
    shop = make_shop(session, "htmlshop")
    shop.platform = "html"
    shop.ingest_config = ingest
    return HtmlShopAdapter(shop)


class TestPriceParsing:
    def test_polish_formats(self):
        assert parse_price("12.00zł") == 12.0
        assert parse_price("12,00 zł") == 12.0
        assert parse_price("1 234,56 PLN") == 1234.56
        assert parse_price("  7.00  ") == 7.0

    def test_rejects_junk_rather_than_guessing(self):
        assert parse_price("") is None
        assert parse_price(None) is None
        assert parse_price("Cena na zapytanie") is None
        # A zero price is never a real grocery price.
        assert parse_price("0,00 zł") is None


class TestStockDetection:
    """These storefronts ship a hidden out-of-stock modal on every page. Reading
    it as a stock signal marked the whole catalogue unavailable."""

    HIDDEN_MODAL = """
      <html><body>
        <h1 class="product-title">TRS Gram Flour 1kg</h1>
        <span class="discounted-unit-price">13.00zł</span>
        <div class="modal" style="display:none">
          <h6 id="out-of-stock-modal-message">Brak w magazynie</h6>
        </div>
      </body></html>
    """

    def test_hidden_modal_does_not_mark_product_unavailable(self, session):
        a = adapter(
            session,
            selectors={"title": ["h1.product-title"], "price": [".discounted-unit-price"]},
        )
        data = a._from_selectors(BeautifulSoup(self.HIDDEN_MODAL, "html.parser"))
        assert data["in_stock"] is True
        assert data["price"] == 13.0

    def test_configured_selector_does_mark_it_unavailable(self, session):
        a = adapter(
            session,
            selectors={
                "title": ["h1.product-title"],
                "price": [".discounted-unit-price"],
                "out_of_stock": "#out-of-stock-modal-message",
            },
        )
        data = a._from_selectors(BeautifulSoup(self.HIDDEN_MODAL, "html.parser"))
        assert data["in_stock"] is False


class TestTitleSize:
    """Pack size is part of product identity, so a title that drops it cannot be
    matched or priced per kg."""

    def test_size_is_recovered_from_the_url_slug(self):
        assert (
            HtmlShopAdapter._title_with_size(
                "TRS Gruba semolina",
                "https://indiancorner.pl/product/trs-coarse-semolina-500g-0tPyR7",
            )
            == "TRS Gruba semolina 500g"
        )

    def test_existing_size_in_the_title_is_left_alone(self):
        assert (
            HtmlShopAdapter._title_with_size(
                "Deep Poha Medium 907g",
                "https://indiancorner.pl/product/deep-poha-medium-907g-gFNSDn",
            )
            == "Deep Poha Medium 907g"
        )

    def test_no_size_anywhere_is_left_alone(self):
        assert (
            HtmlShopAdapter._title_with_size(
                "Brass Kalash", "https://indiancorner.pl/product/brass-kalash-xY12"
            )
            == "Brass Kalash"
        )


class TestJsonLd:
    def test_schema_org_product_is_preferred_when_present(self, session):
        html = """
          <html><head><script type="application/ld+json">
          {"@context":"https://schema.org","@type":"Product",
           "name":"Heera Toor Dal 1kg","sku":"H-TD-1",
           "brand":{"name":"Heera"},"image":["https://x/img.jpg"],
           "offers":{"@type":"Offer","price":"9.99","priceCurrency":"PLN",
                     "availability":"https://schema.org/InStock"}}
          </script></head><body></body></html>
        """
        a = adapter(session)
        data = a._from_jsonld(BeautifulSoup(html, "html.parser"))
        assert data["title"] == "Heera Toor Dal 1kg"
        assert data["price"] == 9.99
        assert data["brand"] == "Heera"
        assert data["in_stock"] is True

    def test_out_of_stock_availability_is_respected(self, session):
        html = """
          <script type="application/ld+json">
          {"@type":"Product","name":"X","offers":{"price":"5.00",
           "priceCurrency":"PLN","availability":"https://schema.org/OutOfStock"}}
          </script>
        """
        data = adapter(session)._from_jsonld(BeautifulSoup(html, "html.parser"))
        assert data["in_stock"] is False

    def test_fragments_sharing_an_id_are_stitched_together(self, session):
        """Shoper splits one product across many <script> tags — name in one,
        price in another, availability in a third — all sharing an "@id".
        Each block read alone looks empty."""
        html = """
        <script type="application/ld+json">
        {"@context":"http://schema.org/","@id":"/pl/p/Kitchen-King/481",
         "@type":"http://schema.org/Product","name":"Przyprawa Kitchen King MDH 100 g",
         "brand":"MDH","image":["https://asianshop.pl/img/481.jpg"]}
        </script>
        <script type="application/ld+json">
        {"@context":"http://schema.org/","@id":"/pl/p/Kitchen-King/481",
         "offers":{"@type":"Offer","price":7.72,"priceCurrency":"PLN"}}
        </script>
        <script type="application/ld+json">
        {"@context":"http://schema.org/","@id":"/pl/p/Kitchen-King/481",
         "offers":{"@type":"Offer","availability":"https://schema.org/InStock"}}
        </script>
        """
        data = adapter(session)._from_jsonld(BeautifulSoup(html, "html.parser"))
        assert data is not None
        assert data["title"] == "Przyprawa Kitchen King MDH 100 g"
        assert data["price"] == 7.72
        assert data["currency"] == "PLN"
        assert data["brand"] == "MDH"
        assert data["in_stock"] is True

    def test_full_iri_type_is_recognised(self, session):
        """@type may be "http://schema.org/Product", not the bare word."""
        html = """
        <script type="application/ld+json">
        {"@type":"http://schema.org/Product","name":"Heera Dal 1kg",
         "offers":{"price":"9.99","priceCurrency":"PLN"}}
        </script>
        """
        data = adapter(session)._from_jsonld(BeautifulSoup(html, "html.parser"))
        assert data is not None and data["price"] == 9.99

    def test_list_value_beats_a_single_dict_when_merging(self, session):
        """Shipping arrives first as one dict, later as the full courier list."""
        dst = {"offers": {"shippingDetails": {"shippingLabel": "partial"}}}
        HtmlShopAdapter._merge(
            dst,
            {"offers": {"shippingDetails": [{"shippingLabel": "DPD"},
                                            {"shippingLabel": "InPost"}]}},
        )
        assert isinstance(dst["offers"]["shippingDetails"], list)
        assert len(dst["offers"]["shippingDetails"]) == 2

    def test_malformed_jsonld_is_skipped_not_fatal(self, session):
        html = '<script type="application/ld+json">{not json at all</script>'
        assert adapter(session)._from_jsonld(BeautifulSoup(html, "html.parser")) is None


class TestUrlFiltering:
    def test_include_and_exclude_patterns(self, session):
        a = adapter(
            session,
            include_pattern=r"/product/",
            exclude_patterns=[r"/category/", r"/blog/"],
        )
        assert a.filter_product_urls(
            [
                "https://htmlshop.example/product/dal-1kg",
                "https://htmlshop.example/category/rice",
                "https://htmlshop.example/product/blog/ignored",
                "https://htmlshop.example/about",
            ]
        ) == ["https://htmlshop.example/product/dal-1kg"]

    def test_http_entries_are_normalised_and_deduplicated(self, session):
        """Sitemaps commonly list http:// while the shop serves https://, which
        would otherwise ingest every product twice."""
        a = adapter(session, include_pattern=r"/product/")
        assert a.filter_product_urls(
            [
                "http://htmlshop.example/product/dal-1kg",
                "https://htmlshop.example/product/dal-1kg",
            ]
        ) == ["https://htmlshop.example/product/dal-1kg"]

    def test_homepage_is_never_treated_as_a_product(self, session):
        a = adapter(session)
        assert a.filter_product_urls(["https://htmlshop.example/"]) == []

    def test_max_products_caps_the_crawl(self, session):
        a = adapter(session, include_pattern=r"/product/", max_products=2)
        urls = [f"https://htmlshop.example/product/item-{i}" for i in range(10)]
        assert len(a.filter_product_urls(urls)) == 2


class TestPlaceholderPrices:
    """Little Asia Grocery lists 78 unrelated products at exactly 1.00 zł. Their
    API returns that faithfully, so it is their data — but ingesting it hands
    that shop the top spot on every product it touches."""

    @staticmethod
    def offers(price, n, start=0):
        from app.ingest.base import RawOffer

        return [
            RawOffer(
                external_id=str(start + i), title=f"item {start + i}",
                url="http://x", price=price, currency="PLN",
            )
            for i in range(n)
        ]

    def test_repeated_low_price_is_detected(self):
        from app.ingest.runner import detect_placeholder_prices

        catalogue = self.offers(1.0, 78) + self.offers(12.0, 300, start=100)
        assert detect_placeholder_prices(catalogue) == {1.0}

    def test_a_few_genuinely_cheap_items_are_kept(self):
        from app.ingest.runner import detect_placeholder_prices

        catalogue = self.offers(1.0, 2) + self.offers(5.0, 200, start=100)
        assert detect_placeholder_prices(catalogue) == set()

    def test_normal_prices_are_never_flagged_however_common(self):
        """9.99 appears 141 times in India Bazaar's catalogue and is real."""
        from app.ingest.runner import detect_placeholder_prices

        assert detect_placeholder_prices(self.offers(9.99, 141)) == set()

    def test_empty_catalogue(self):
        from app.ingest.runner import detect_placeholder_prices

        assert detect_placeholder_prices([]) == set()
