import { useState } from "react";
import { type ProductSummary, type ShopPrice, zl } from "../lib/api";

interface Props {
  product: ProductSummary;
  onCompare: (slug: string) => void;
  onAdd: (id: number, name: string) => void;
}

const VISIBLE_SHOPS = 3;

/**
 * Per-shop pricing for one product.
 *
 * Deliberately shows the product price only. Estimated delivery was shown here
 * once and removed: only two of the shops publish real rates, so most rows were
 * guesses sitting next to real prices, which is worse than showing nothing.
 * Delivery still drives the basket optimiser, where thresholds are real and
 * apply to the whole order.
 */
function ShopRow({ row, best }: { row: ShopPrice; best: boolean }) {
  return (
    <a
      className={`shop-row${best ? " best" : ""}${row.in_stock ? "" : " out"}`}
      href={row.url}
      target="_blank"
      rel="noopener nofollow"
      title={`${row.shop_name} — open in shop`}
    >
      <span className="shop-name">
        {row.shop_name}
        {row.free_over_pln != null && (
          <span
            className="free-over"
            title={`This shop delivers free on orders over ${Math.round(
              row.free_over_pln,
            )} zł`}
          >
            free delivery over {Math.round(row.free_over_pln)} zł
          </span>
        )}
      </span>
      <span className="shop-price">{zl(row.price_pln)}</span>
    </a>
  );
}

export function ProductCard({ product, onCompare, onAdd }: Props) {
  const [imageFailed, setImageFailed] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const rows = product.shop_prices ?? [];
  const inStock = rows.filter((r) => r.in_stock);
  const shown = expanded ? rows : rows.slice(0, VISIBLE_SHOPS);
  const hidden = rows.length - shown.length;
  const showImage = product.image_url && !imageFailed;

  const cheapest = inStock[0]?.price_pln;
  const dearest =
    inStock.length > 1 ? inStock[inStock.length - 1].price_pln : null;
  const saving = cheapest != null && dearest != null ? dearest - cheapest : null;

  return (
    <article className="card product">
      <div className="product-head">
        {showImage ? (
          <img
            className="thumb"
            src={product.image_url!}
            alt=""
            loading="lazy"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <div className="thumb placeholder" aria-hidden="true">
            🛒
          </div>
        )}
        <div className="product-id">
          <h3>{product.name}</h3>
          <div className="sub">
            {product.brand && <span className="brand">{product.brand}</span>}
            {product.best_unit_price_pln != null && product.base_unit && (
              <span>
                {zl(product.best_unit_price_pln)}/{product.base_unit}
              </span>
            )}
          </div>
        </div>
      </div>

      {rows.length > 0 ? (
        <>
          {/* No Shop/Price column header: it is a header for one to three
              rows, and at 60 cards a screen that chrome was louder than the
              prices it labelled. */}
          <div className="shop-table">
            {shown.map((row, i) => (
              <ShopRow key={row.shop_slug} row={row} best={i === 0 && !expanded} />
            ))}
          </div>

          {hidden > 0 && (
            <button className="more" onClick={() => setExpanded(true)}>
              + {hidden} more {hidden === 1 ? "shop" : "shops"}
            </button>
          )}
          {expanded && rows.length > VISIBLE_SHOPS && (
            <button className="more" onClick={() => setExpanded(false)}>
              show less
            </button>
          )}
        </>
      ) : (
        <div className="sub">No offers available</div>
      )}

      {saving != null && saving > 0.5 && inStock.length > 1 && (
        <div className="saving-banner">
          Save <b>{zl(saving)}</b> at {inStock[0].shop_name}
        </div>
      )}

      <div className="row-actions">
        <button onClick={() => onCompare(product.slug)}>
          Compare
          {rows.length > 1 && <span className="count">{rows.length}</span>}
        </button>
        <button className="primary" onClick={() => onAdd(product.id, product.name)}>
          + list
        </button>
      </div>
    </article>
  );
}
