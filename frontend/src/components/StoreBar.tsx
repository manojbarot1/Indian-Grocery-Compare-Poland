import type { Shop } from "../lib/api";

interface Props {
  shops: Shop[];
  active: string | null;
  onSelect: (slug: string | null) => void;
}

/**
 * Browse by shop.
 *
 * Sits beside the category list rather than inside the shop *directory* in the
 * right column: this one is a filter, that one is reference information, and
 * mixing the two is what made the old sidebar confusing.
 */
export function StoreBar({ shops, active, onSelect }: Props) {
  const stocked = shops
    .filter((shop) => shop.offer_count > 0)
    .sort((a, b) => b.offer_count - a.offer_count);

  if (!stocked.length) return null;

  return (
    <nav className="cats card stores" aria-label="Shops">
      <h2>
        Shops
        {/* No "All shops" row: it carried a count that meant something
            different from every other number in the list, and with nothing
            selected the list already shows everything. Clearing only needs to
            exist once there is something to clear. */}
        {active && (
          <button className="clear-filter" onClick={() => onSelect(null)}>
            clear
          </button>
        )}
      </h2>
      <ul>
        {stocked.map((shop) => (
          <li key={shop.slug}>
            <button
              className={active === shop.slug ? "active" : ""}
              onClick={() => onSelect(active === shop.slug ? null : shop.slug)}
              title={`${shop.name} — ${shop.offer_count.toLocaleString("en")} offers`}
            >
              <span>{shop.name}</span>
              <span className="n">{shop.offer_count.toLocaleString("en")}</span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
