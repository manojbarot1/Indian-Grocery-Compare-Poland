import { useState } from "react";
import { type BasketResult, optimizeBasket, type Parcel, zl } from "../lib/api";
import type { Basket } from "../lib/useBasket";

interface Props {
  basket: Basket;
  items: { product_id: number; quantity: number }[];
  onSetQuantity: (id: number, quantity: number) => void;
  onRemove: (id: number) => void;
  onClear: () => void;
}

function ParcelCard({ parcel }: { parcel: Parcel }) {
  return (
    <div className="parcel">
      <h4>{parcel.shop_name}</h4>
      <div className="meta">
        {zl(parcel.subtotal_pln)} + delivery{" "}
        {parcel.free_shipping_applied ? (
          <b className="free">free</b>
        ) : (
          <>
            {zl(parcel.shipping_pln)}
            {parcel.shipping_estimated && parcel.shipping_pln > 0 && " (est.)"}
          </>
        )}{" "}
        · {parcel.min_days}–{parcel.max_days} days ·{" "}
        {(parcel.weight_grams / 1000).toFixed(1)} kg
      </div>
      <div className="parcel-items">
        {parcel.items.map((item) => (
          <div key={item.product_id}>
            {item.quantity} × {item.product_name}{" "}
            <span className="meta">{zl(item.line_total_pln)}</span>
          </div>
        ))}
      </div>
      {parcel.amount_to_free_shipping != null && parcel.amount_to_free_shipping > 0 && (
        <div className="meta hint">
          spend {zl(parcel.amount_to_free_shipping)} more here for free delivery
        </div>
      )}
      {parcel.warnings.map((warning) => (
        <div className="warn" key={warning}>
          {warning}
        </div>
      ))}
    </div>
  );
}

export function BasketPanel({ basket, items, onSetQuantity, onRemove, onClear }: Props) {
  const [result, setResult] = useState<BasketResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ids = Object.keys(basket).map(Number);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await optimizeBasket(items));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  if (!ids.length) {
    return (
      <div className="card pad basket-empty">
        <h2>Shopping list</h2>
        <p className="meta empty-note">
          Add products and we will work out the <b>cheapest way to split</b> your
          order across shops, delivery included.
        </p>
        <p className="meta empty-note">
          Buying each item wherever it is cheapest usually costs more — you pay
          for several parcels.
        </p>
      </div>
    );
  }

  const best = result?.best;

  return (
    <div className="card pad">
      <div className="panel-head">
        <h2>Shopping list ({ids.length})</h2>
        <button className="link" onClick={onClear}>
          clear
        </button>
      </div>

      {ids.map((id) => (
        <div className="basket-item" key={id}>
          <span>{basket[id].name}</span>
          <input
            type="number"
            min={1}
            max={99}
            value={basket[id].quantity}
            onChange={(event) => onSetQuantity(id, Number(event.target.value))}
          />
          <button className="link" onClick={() => onRemove(id)} title="Remove">
            ×
          </button>
        </div>
      ))}

      <button className="primary wide" onClick={run} disabled={busy}>
        {busy ? "Calculating…" : "Find cheapest split"}
      </button>

      {error && <div className="warn">{error}</div>}

      {best && (
        <div className="plan">
          <div className="totals">
            <div>
              total delivered <b>{zl(best.total_pln)}</b>
            </div>
            <div>
              goods <b>{zl(best.goods_pln)}</b>
            </div>
            <div>
              delivery <b>{zl(best.shipping_pln)}</b>
            </div>
          </div>

          {result!.savings_vs_single_shop_pln > 0.009 && (
            <p className="meta saving">
              You save <b>{zl(result!.savings_vs_single_shop_pln)}</b> versus buying
              everything in one shop ({zl(result!.single_shop!.total_pln)}).
            </p>
          )}
          {result!.savings_vs_naive_pln > 0.009 && (
            <p className="meta saving">
              And <b>{zl(result!.savings_vs_naive_pln)}</b> versus buying each item
              wherever it is cheapest ({result!.naive!.parcels.length} parcels,{" "}
              {zl(result!.naive!.total_pln)}).
            </p>
          )}
          {result!.missing_product_ids.length > 0 && (
            <div className="warn">
              {result!.missing_product_ids.length} item(s) not available from any
              shop delivering to Poland.
            </div>
          )}

          {best.parcels.map((parcel) => (
            <ParcelCard parcel={parcel} key={parcel.shop_slug} />
          ))}
        </div>
      )}
    </div>
  );
}
