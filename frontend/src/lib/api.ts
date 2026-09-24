export interface ShopPrice {
  shop_slug: string;
  shop_name: string;
  price_pln: number;
  shipping_pln: number | null;
  landed_total_pln: number | null;
  shipping_estimated: boolean;
  free_shipping_applied: boolean;
  in_stock: boolean;
  min_days: number | null;
  max_days: number | null;
  url: string;
  free_over_pln: number | null;
  amount_to_free_shipping: number | null;
}

export interface ProductSummary {
  id: number;
  slug: string;
  name: string;
  brand: string | null;
  image_url: string | null;
  base_unit: string | null;
  offer_count: number;
  shop_count: number;
  min_price_pln: number | null;
  max_price_pln: number | null;
  best_unit_price_pln: number | null;
  best_landed_pln: number | null;
  spread_pct: number | null;
  shop_prices: ShopPrice[];
}

export interface Offer {
  id: number;
  shop_slug: string;
  shop_name: string;
  title: string;
  url: string;
  price_pln: number;
  unit_price_pln: number | null;
  base_unit: string | null;
  in_stock: boolean;
  shipping_pln: number | null;
  shipping_method: string | null;
  shipping_estimated: boolean;
  free_shipping_applied: boolean;
  amount_to_free_shipping: number | null;
  landed_total_pln: number | null;
  min_days: number | null;
  max_days: number | null;
  warnings: string[];
}

export interface ProductDetail extends ProductSummary {
  offers: Offer[];
}

export interface SearchResponse {
  query: string | null;
  total: number;
  page: number;
  page_size: number;
  results: ProductSummary[];
  hidden_single_shop: number;
}

export interface Shop {
  slug: string;
  name: string;
  url: string;
  country: string;
  currency: string;
  offer_count: number;
  shipping_confidence: string;
  free_over: number | null;
}

export interface ParcelItem {
  product_id: number;
  product_name: string;
  quantity: number;
  offer_title: string;
  offer_url: string;
  line_total_pln: number;
}

export interface Parcel {
  shop_slug: string;
  shop_name: string;
  items: ParcelItem[];
  subtotal_pln: number;
  shipping_pln: number;
  shipping_method: string;
  shipping_estimated: boolean;
  free_shipping_applied: boolean;
  amount_to_free_shipping: number | null;
  weight_grams: number;
  min_days: number;
  max_days: number;
  warnings: string[];
  total_pln: number;
}

export interface BasketPlan {
  strategy: string;
  parcels: Parcel[];
  goods_pln: number;
  shipping_pln: number;
  total_pln: number;
  max_days: number;
  any_estimated_shipping: boolean;
}

export interface BasketResult {
  best: BasketPlan | null;
  single_shop: BasketPlan | null;
  naive: BasketPlan | null;
  missing_product_ids: number[];
  savings_vs_naive_pln: number;
  savings_vs_single_shop_pln: number;
}

export interface SubCategory {
  slug: string;
  label: string;
  count: number;
}

export interface Category {
  slug: string;
  label: string;
  count: number;
  children: SubCategory[];
}

export interface Stats {
  shops: number;
  offers: number;
  products: number;
  products_in_multiple_shops: number;
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json() as Promise<T>;
}

export interface SearchParams {
  q?: string;
  sort?: string;
  multiShopOnly?: boolean;
  category?: string | null;
  subcategory?: string | null;
  shop?: string | null;
  page?: number;
  pageSize?: number;
}

export function search(params: SearchParams): Promise<SearchResponse> {
  const query = new URLSearchParams({
    sort: params.sort ?? "price",
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 60),
    multi_shop_only: String(params.multiShopOnly ?? false),
  });
  if (params.q) query.set("q", params.q);
  if (params.category) query.set("category", params.category);
  if (params.shop) query.set("shop", params.shop);
  if (params.subcategory) query.set("subcategory", params.subcategory);
  return get<SearchResponse>(`/search?${query}`);
}

export const getCategories = (multiShopOnly = false) =>
  get<{ categories: Category[]; total: number }>(
    `/categories?multi_shop_only=${multiShopOnly}`,
  );

export const getProduct = (slug: string, quantity = 1) =>
  get<ProductDetail>(`/products/${slug}?quantity=${quantity}`);

export const getShops = () => get<Shop[]>("/shops");

export const getStats = () => get<Stats>("/stats");

export async function optimizeBasket(
  items: { product_id: number; quantity: number }[],
): Promise<BasketResult> {
  const response = await fetch("/api/basket/optimize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export const zl = (value: number | null | undefined): string =>
  value == null ? "—" : `${value.toFixed(2)} zł`;
