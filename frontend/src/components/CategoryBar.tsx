import { Fragment } from "react";
import type { Category } from "../lib/api";

interface Props {
  categories: Category[];
  total: number;
  active: string | null;
  activeSub: string | null;
  onSelect: (slug: string | null) => void;
  onSelectSub: (slug: string | null) => void;
}

/**
 * Category list with one level of sub-categories.
 *
 * Children appear only under the open category. Showing every sub-category at
 * once would be a 60-item wall, and the whole point of the split is that
 * "Flour & Atta, 201 products" is a list rather than a filter — wheat atta,
 * besan and semolina are different shopping decisions.
 */
export function CategoryBar({
  categories,
  total,
  active,
  activeSub,
  onSelect,
  onSelectSub,
}: Props) {
  return (
    <nav className="cats card" aria-label="Categories">
      <h2>Categories</h2>
      <ul>
        <li>
          <button
            className={active === null ? "active" : ""}
            onClick={() => onSelect(null)}
          >
            <span>All products</span>
            <span className="n">{total.toLocaleString("en")}</span>
          </button>
        </li>
        {categories.map((category) => (
          <Fragment key={category.slug}>
            <li>
              <button
                className={active === category.slug ? "active" : ""}
                onClick={() =>
                  onSelect(active === category.slug ? null : category.slug)
                }
              >
                <span>{category.label}</span>
                <span className="n">{category.count.toLocaleString("en")}</span>
              </button>
            </li>
            {active === category.slug &&
              category.children.map((child) => (
                <li key={child.slug} className="sub">
                  <button
                    className={activeSub === child.slug ? "active" : ""}
                    onClick={() =>
                      onSelectSub(activeSub === child.slug ? null : child.slug)
                    }
                  >
                    <span>{child.label}</span>
                    <span className="n">{child.count.toLocaleString("en")}</span>
                  </button>
                </li>
              ))}
          </Fragment>
        ))}
      </ul>
    </nav>
  );
}
