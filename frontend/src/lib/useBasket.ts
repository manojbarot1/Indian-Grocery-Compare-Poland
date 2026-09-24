import { useCallback, useEffect, useState } from "react";

export interface BasketLine {
  name: string;
  quantity: number;
}

export type Basket = Record<number, BasketLine>;

const STORAGE_KEY = "desicena.basket";

function load(): Basket {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Basket;
  } catch {
    return {};
  }
}

export function useBasket() {
  const [basket, setBasket] = useState<Basket>(load);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(basket));
  }, [basket]);

  const add = useCallback((id: number, name: string) => {
    setBasket((current) => ({
      ...current,
      [id]: { name, quantity: (current[id]?.quantity ?? 0) + 1 },
    }));
  }, []);

  const setQuantity = useCallback((id: number, quantity: number) => {
    setBasket((current) =>
      current[id]
        ? { ...current, [id]: { ...current[id], quantity: Math.max(1, quantity) } }
        : current,
    );
  }, []);

  const remove = useCallback((id: number) => {
    setBasket((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
  }, []);

  const clear = useCallback(() => setBasket({}), []);

  const items = Object.entries(basket).map(([id, line]) => ({
    product_id: Number(id),
    quantity: line.quantity,
  }));

  return { basket, add, setQuantity, remove, clear, items };
}
