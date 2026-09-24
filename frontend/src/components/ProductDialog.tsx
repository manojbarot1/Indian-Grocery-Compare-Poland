import { Fragment, useEffect, useState } from "react";
import { getProduct, type ProductDetail, zl } from "../lib/api";

interface Props {
  slug: string | null;
  onClose: () => void;
}

export function ProductDialog({ slug, onClose }: Props) {
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [quantity, setQuantity] = useState(1);

  useEffect(() => {
    if (!slug) {
      setProduct(null);
      return;
    }
    let cancelled = false;
    getProduct(slug, quantity).then((data) => {
      if (!cancelled) setProduct(data);
    });
    return () => {
      cancelled = true;
    };
  }, [slug, quantity]);

  useEffect(() => {
    setQuantity(1);
  }, [slug]);

  if (!slug) return null;

  return (
    <div className="backdrop" onClick={onClose}>
      <div className="dialog" onClick={(event) => event.stopPropagation()}>
        <div className="dlg-head">
          <div style={{ flex: 1 }}>
            <h3>{product?.name ?? "…"}</h3>
            {product && (
              <div className="dlg-summary">
                {/* "Where can I buy this" is the question the dialog answers,
                    so the shop count leads instead of sitting in metadata. */}
                <b>
                  Available in {product.shop_count}{" "}
                  {product.shop_count === 1 ? "shop" : "shops"}
                </b>
                {product.min_price_pln != null && product.max_price_pln != null && (
                  <span className="meta">
                    {zl(product.min_price_pln)} – {zl(product.max_price_pln)}
                    {product.spread_pct != null && product.spread_pct >= 1 && (
                      <> · {product.spread_pct}% spread</>
                    )}
                  </span>
                )}
                {product.brand && <span className="pill">{product.brand}</span>}
              </div>
            )}
          </div>
          <label className="check">
            qty
            <input
              type="number"
              min={1}
              max={99}
              value={quantity}
              onChange={(event) => setQuantity(Math.max(1, Number(event.target.value)))}
            />
          </label>
          <button onClick={onClose}>Close</button>
        </div>

        <div className="dlg-body">
          {!product ? (
            <p className="meta">Loading…</p>
          ) : (
            <>
              <table>
                <thead>
                  <tr>
                    <th>Shop</th>
                    <th className="num">Price</th>
                    <th className="num">Per unit</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {product.offers.map((offer, index) => (
                    <Fragment key={offer.id}>
                      <tr className={index === 0 && offer.in_stock ? "best" : ""}>
                        <td>
                          <b>{offer.shop_name}</b>
                          {!offer.in_stock && <span className="pill grey">out of stock</span>}
                          <div className="meta">{offer.title}</div>
                        </td>
                        <td className="num">{zl(offer.price_pln)}</td>
                        <td className="num">
                          {offer.unit_price_pln != null && offer.base_unit
                            ? `${zl(offer.unit_price_pln)}/${offer.base_unit}`
                            : "—"}
                        </td>
                        <td>
                          <a href={offer.url} target="_blank" rel="noopener nofollow">
                            go →
                          </a>
                        </td>
                      </tr>
                      {offer.amount_to_free_shipping != null &&
                        offer.amount_to_free_shipping > 0 && (
                          <tr>
                            <td colSpan={4} className="meta hint">
                              spend {zl(offer.amount_to_free_shipping)} more at{" "}
                              {offer.shop_name} for free delivery
                            </td>
                          </tr>
                        )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
              <p className="meta footnote">
                Product prices only — delivery is not included. Most shops quote
                it at checkout. Use the shopping list to compare full orders.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
