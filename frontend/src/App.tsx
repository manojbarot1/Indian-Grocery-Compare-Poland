import { useCallback, useEffect, useState } from "react";
import { BasketPanel } from "./components/BasketPanel";
import { ProductCard } from "./components/ProductCard";
import { ProductDialog } from "./components/ProductDialog";
import { ShopsPanel } from "./components/ShopsPanel";
import { CategoryBar } from "./components/CategoryBar";
import { StoreBar } from "./components/StoreBar";
import {
  type Category,
  getCategories,
  getShops,
  getStats,
  search,
  timeAgo,
  exactTime,
  type SearchResponse,
  type Shop,
  type Stats,
} from "./lib/api";
import { useBasket } from "./lib/useBasket";
import { useGlassGlint } from "./lib/useGlassGlint";

const SORTS = [
  { value: "price", label: "Sort: lowest price" },
  { value: "unit", label: "Sort: cheapest per kg/l" },
  { value: "offers", label: "Sort: most shops" },
  { value: "name", label: "Sort: name A–Z" },
];

export default function App() {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [sort, setSort] = useState("price");
  // Show everything by default. Filtering to multi-shop products hid 37 of 38
  // parathas, which reads as "we don't stock it" rather than "only one shop
  // has it" — the wrong answer to give someone searching for a real product.
  const [multiShopOnly, setMultiShopOnly] = useState(false);
  const [page, setPage] = useState(1);

  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [shops, setShops] = useState<Shop[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [openSlug, setOpenSlug] = useState<string | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryTotal, setCategoryTotal] = useState(0);
  const [category, setCategory] = useState<string | null>(null);
  const [subcategory, setSubcategory] = useState<string | null>(null);
  const [shopFilter, setShopFilter] = useState<string | null>(null);
  // Mobile only: the rail is 714px of filters sitting above the results.
  const [filtersOpen, setFiltersOpen] = useState(false);

  const { basket, add, setQuantity, remove, clear, items } = useBasket();
  useGlassGlint();

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(query.trim());
      setPage(1);
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    search({
      q: debounced, sort, multiShopOnly, category, subcategory,
      shop: shopFilter, page,
    })
      .then((response) => {
        if (!cancelled) setData(response);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debounced, sort, multiShopOnly, category, subcategory, shopFilter, page]);

  useEffect(() => {
    getShops().then(setShops);
    getStats().then(setStats);
  }, []);

  // Counts follow the comparable-only filter so the sidebar never promises
  // more products than the active filter will show.
  useEffect(() => {
    getCategories(multiShopOnly).then((data) => {
      setCategories(data.categories);
      setCategoryTotal(data.total);
    });
  }, [multiShopOnly]);

  // Publish the sticky header's height so the filter rail can sit below it.
  // Measured rather than hard-coded because the toolbar wraps to two rows on
  // narrow screens — but measuring is racy: on first paint the stylesheet has
  // not applied yet and the unstyled header measures ~550px, which then stuck.
  // So: re-measure on load and resize as well, and ignore implausible values.
  useEffect(() => {
    const header = document.querySelector("header");
    if (!header) return;

    const apply = () => {
      const height = header.getBoundingClientRect().height;
      if (height > 0 && height < 320) {
        document.documentElement.style.setProperty("--header-h", `${height}px`);
      }
    };

    // Retry briefly: in dev the stylesheet arrives after first paint, so the
    // first measurements are of an unstyled header and get rejected above.
    // Observers alone did not recover from that reliably.
    apply();
    const retries = [0, 50, 150, 400, 1000].map((delay) =>
      window.setTimeout(apply, delay),
    );
    const observer = new ResizeObserver(apply);
    observer.observe(header);
    window.addEventListener("load", apply);
    window.addEventListener("resize", apply);
    return () => {
      retries.forEach(window.clearTimeout);
      observer.disconnect();
      window.removeEventListener("load", apply);
      window.removeEventListener("resize", apply);
    };
  }, []);

  const goto = useCallback((next: number) => {
    setPage(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const pages = data ? Math.ceil(data.total / data.page_size) : 0;
  const hiddenCount = multiShopOnly ? (data?.hidden_single_shop ?? 0) : 0;

  return (
    <>
      {/* The scene the glass refracts. Fixed and behind everything, so panels
          sample the same colours while the page scrolls under them. */}
      <div className="bg-canvas" aria-hidden="true">
        <div className="ambient-orb orb-1" />
        <div className="ambient-orb orb-2" />
        <div className="ambient-orb orb-3" />
      </div>

      <header>
        <div className="wrap bar">
          <div className="logo">
            Desi<span>Price</span>{" "}
            <span className="tag">Indian groceries · Poland</span>
          </div>
          <input
            type="search"
            value={query}
            placeholder="Search: basmati, atta, ghee, garam masala…"
            onChange={(event) => setQuery(event.target.value)}
          />
          <select value={sort} onChange={(event) => setSort(event.target.value)}>
            {SORTS.map((option) => (
              <option value={option.value} key={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <label
            className="check"
            title="Hide products that only one shop sells, leaving just the ones you can actually compare"
          >
            <input
              type="checkbox"
              checked={multiShopOnly}
              onChange={(event) => setMultiShopOnly(event.target.checked)}
            />
            in 2+ shops only
          </label>
        </div>
        {/* One line saying what the site does. Without it the price columns
            look like an ordinary shop listing. */}
        <div className="wrap explainer">
          <span>
            The same product, <b>priced across every Indian grocery shop in
            Poland</b> — so you can see who actually sells it cheapest.
          </span>
          {stats && (
            <span className="explainer-stats">
              {stats.offers.toLocaleString("en")} offers · {stats.shops} shops ·{" "}
              {stats.products_in_multiple_shops.toLocaleString("en")} products to
              compare
            </span>
          )}
          {stats && (
            <span
              className="freshness"
              title={
                stats.last_refreshed
                  ? `Newest shop data: ${exactTime(stats.last_refreshed)}\nOldest: ${exactTime(stats.oldest_refreshed)}`
                  : "No successful refresh recorded yet"
              }
            >
              <span className="freshness-dot" />
              Prices updated {timeAgo(stats.last_refreshed)}
            </span>
          )}
        </div>
      </header>

      <main className="wrap layout">
        {/* One sticky rail, not two sticky blocks: independently sticky
            siblings in separate grid rows slid over each other on scroll. */}
        <button
          className="filters-toggle"
          onClick={() => setFiltersOpen((open) => !open)}
          aria-expanded={filtersOpen}
        >
          {filtersOpen ? "Hide filters" : "Filters"}
          {(category || shopFilter) && <span className="dot-on" />}
        </button>

        <aside className={`rail${filtersOpen ? " open" : ""}`}>
          <CategoryBar
            categories={categories}
            total={categoryTotal}
            active={category}
            activeSub={subcategory}
            onSelect={(slug) => {
              setCategory(slug);
              // A sub-category only means something inside its parent.
              setSubcategory(null);
              setPage(1);
            }}
            onSelectSub={(slug) => {
              setSubcategory(slug);
              setPage(1);
              setFiltersOpen(false);
            }}
          />

          <StoreBar
            shops={shops}
            active={shopFilter}
            onSelect={(slug) => {
              setShopFilter(slug);
              setPage(1);
            }}
          />
        </aside>

        <section>
          <div className="meta status">
            {loading
              ? "Searching…"
              : `${(data?.total ?? 0).toLocaleString("en")} products${
                  debounced ? ` for “${debounced}”` : ""
                }`}
          </div>

          {!loading && data?.results.length === 0 ? (
            <div className="card empty">
              {hiddenCount > 0 ? (
                <>
                  <p className="empty-title">
                    Nothing here is sold by more than one shop
                  </p>
                  <p>
                    {hiddenCount} matching {hiddenCount === 1 ? "product" : "products"}{" "}
                    {hiddenCount === 1 ? "is" : "are"} available, but only from a
                    single shop — so there is nothing to compare.
                  </p>
                  <button className="primary" onClick={() => setMultiShopOnly(false)}>
                    Show them anyway
                  </button>
                </>
              ) : (
                <>
                  <p className="empty-title">
                    {debounced ? `No match for “${debounced}”` : "Nothing to show"}
                  </p>
                  <p>
                    Try a shorter or more general term — a brand like{" "}
                    <em>MDH</em>, or a product like <em>atta</em> or{" "}
                    <em>basmati</em>.
                  </p>
                </>
              )}
            </div>
          ) : (
            <div className="grid">
              {data?.results.map((product) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  onCompare={setOpenSlug}
                  onAdd={add}
                />
              ))}
            </div>
          )}

          {/* Never silently swallow matches: a shopper searching for something
              only one shop stocks should be told it exists. */}
          {!loading && hiddenCount > 0 && (data?.results.length ?? 0) > 0 && (
            <div className="hidden-note">
              {hiddenCount} more {hiddenCount === 1 ? "product matches" : "products match"}{" "}
              but {hiddenCount === 1 ? "is" : "are"} sold by only one shop.{" "}
              <button className="link-inline" onClick={() => setMultiShopOnly(false)}>
                Show all
              </button>
            </div>
          )}

          {pages > 1 && (
            <div className="pager">
              <button disabled={page <= 1} onClick={() => goto(page - 1)}>
                ← back
              </button>
              <span className="meta">
                {page} / {pages}
              </span>
              <button disabled={page >= pages} onClick={() => goto(page + 1)}>
                next →
              </button>
            </div>
          )}
        </section>

        <aside className="side">
          <BasketPanel
            basket={basket}
            items={items}
            onSetQuantity={setQuantity}
            onRemove={remove}
            onClear={clear}
          />

          <ShopsPanel shops={shops} />
        </aside>
      </main>

      <ProductDialog slug={openSlug} onClose={() => setOpenSlug(null)} />
    </>
  );
}
