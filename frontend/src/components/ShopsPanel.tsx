import { useState } from "react";
import { type Shop, timeAgo, exactTime } from "../lib/api";

/**
 * Shop directory.
 *
 * Deliberately collapsed by default and one line per shop when open. This is
 * reference information a shopper checks once, not something they scan while
 * comparing products — at three lines each it was out-shouting the results.
 */
export function ShopsPanel({ shops }: { shops: Shop[] }) {
  const [open, setOpen] = useState(false);

  const totalOffers = shops.reduce((sum, s) => sum + s.offer_count, 0);
  const confirmed = shops.filter((s) => s.shipping_confidence === "high").length;
  const sorted = [...shops].sort((a, b) => b.offer_count - a.offer_count);

  return (
    <div className="card shops-card">
      <button
        className="shops-toggle"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span className="shops-title">
          {shops.length} shops
          <span className="meta"> · {totalOffers.toLocaleString("en")} offers</span>
        </span>
        <span className="chev">{open ? "−" : "+"}</span>
      </button>

      {open && (
        <div className="shops-body">
          <table className="shops-table">
            <tbody>
              {sorted.map((shop) => (
                <tr key={shop.slug}>
                  <td>
                    <span
                      className={`dot ${
                        shop.shipping_confidence === "high" ? "ok" : "est"
                      }`}
                      title={
                        shop.shipping_confidence === "high"
                          ? "Delivery rates published by the shop"
                          : "Shop quotes delivery only at checkout — our figure is estimated"
                      }
                    />
                    <a href={shop.url} target="_blank" rel="noopener nofollow">
                      {shop.name}
                    </a>
                    {shop.country !== "PL" && (
                      <span className="meta abroad" title={`Ships from ${shop.country}`}>
                        {shop.country}
                      </span>
                    )}
                  </td>
                  <td className="free-col">
                    {shop.free_over != null && (
                      <span className="meta">free {Math.round(shop.free_over)}+</span>
                    )}
                  </td>
                  <td className="num" title={exactTime(shop.last_ingest_at)}>
                    {shop.offer_count.toLocaleString("en")}
                    <span className="shop-age">{timeAgo(shop.last_ingest_at)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="legend">
            <span className="dot ok" /> rates published · <span className="dot est" />{" "}
            estimated ({shops.length - confirmed} of {shops.length})
          </p>
        </div>
      )}
    </div>
  );
}
