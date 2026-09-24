"""DesiPrice operator CLI.

    python cli.py init                 create tables, load shops.yaml
    python cli.py ingest               pull every active shop
    python cli.py ingest --shop dookan pull one shop
    python cli.py match                collapse offers into products
    python cli.py refresh              ingest + match + prune
    python cli.py stats                what is in the database
    python cli.py inspect "basmati"    see how a title normalises and matches
    python cli.py basket 12:2 44:1     optimise a basket of product_id:qty
"""

from __future__ import annotations

import typer
from sqlalchemy import func, select

from app.basket.optimizer import optimize_basket
from app.db import SessionLocal, init_db
from app.ingest.registry import load_shops
from app.ingest.runner import ingest_all
from app.matching.matcher import match_offers, prune_orphan_products
from app.matching.normalize import parse_title
from app.models import Offer, Product, Shop

cli = typer.Typer(add_completion=False, help="DesiPrice operator CLI")


@cli.command()
def init():
    """Create tables and sync shops.yaml into the database."""
    init_db()
    with SessionLocal() as session:
        shops = load_shops(session)
    typer.echo(f"initialised; {len(shops)} shops registered")
    for shop in shops:
        typer.echo(f"  - {shop.slug:18} {shop.platform:12} {shop.currency}  {shop.url}")


@cli.command()
def ingest(
    shop: list[str] = typer.Option(None, "--shop", help="Limit to these slugs"),
    dry_run: bool = typer.Option(False, help="Fetch and count, write nothing"),
):
    """Pull catalogues from the shops."""
    init_db()
    with SessionLocal() as session:
        load_shops(session)
        results = ingest_all(session, only=list(shop) if shop else None, dry_run=dry_run)

    for result in results:
        if result.ok:
            typer.echo(
                f"  {result.shop_slug:18} fetched={result.fetched:<6} "
                f"new={result.created:<5} upd={result.updated:<6} "
                f"price_changes={result.price_changes:<5} delisted={result.delisted} "
                f"placeholder={result.skipped_placeholder}"
            )
        else:
            typer.secho(f"  {result.shop_slug:18} FAILED  {result.error}", fg="red")

    failures = [r for r in results if not r.ok]
    typer.echo(f"\n{len(results) - len(failures)}/{len(results)} shops ingested")
    if failures:
        raise typer.Exit(code=1)


@cli.command()
def match(
    rematch_all: bool = typer.Option(False, help="Re-evaluate already-matched offers"),
):
    """Collapse shop offers into canonical products."""
    init_db()
    with SessionLocal() as session:
        stats_ = match_offers(session, rematch_all=rematch_all)
        pruned = prune_orphan_products(session)
    typer.echo(
        f"matched={stats_['matched']} created={stats_['created']} "
        f"skipped={stats_['skipped']} pruned={pruned}"
    )


@cli.command()
def refresh(shop: list[str] = typer.Option(None, "--shop")):
    """ingest + match + prune, the full nightly job."""
    ingest(shop=shop, dry_run=False)
    match(rematch_all=False)


@cli.command("reset-matches")
def reset_matches(
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt"),
):
    """Clear all canonical products and unlink offers, keeping offers intact.

    Use this instead of touching the tables by hand: `TRUNCATE products CASCADE`
    silently takes `offers` with it, because offers reference products.
    """
    if not yes:
        typer.confirm(
            "Delete all canonical products and unlink every offer?", abort=True
        )
    init_db()
    with SessionLocal() as session:
        session.query(Offer).update(
            {Offer.product_id: None, Offer.match_score: None}, synchronize_session=False
        )
        removed = session.query(Product).delete(synchronize_session=False)
        session.commit()
        remaining = session.scalar(select(func.count(Offer.id)))
    typer.echo(f"removed {removed} products; {remaining} offers preserved")


@cli.command()
def stats():
    """Summarise the database."""
    init_db()
    with SessionLocal() as session:
        typer.echo(f"shops    : {session.scalar(select(func.count(Shop.id)))}")
        typer.echo(f"offers   : {session.scalar(select(func.count(Offer.id)))}")
        typer.echo(f"products : {session.scalar(select(func.count(Product.id)))}")

        rows = session.execute(
            select(Shop.name, func.count(Offer.id), func.min(Offer.price_pln))
            .join(Offer, Offer.shop_id == Shop.id)
            .group_by(Shop.name)
            .order_by(func.count(Offer.id).desc())
        ).all()
        typer.echo("\nper shop:")
        for name, count, cheapest in rows:
            typer.echo(f"  {name:22} {count:>6} offers   from {cheapest:.2f} PLN")

        comparable = (
            select(Offer.product_id)
            .group_by(Offer.product_id)
            .having(func.count(func.distinct(Offer.shop_id)) > 1)
            .subquery()
        )
        typer.echo(
            f"\nproducts sold by 2+ shops: "
            f"{session.scalar(select(func.count()).select_from(comparable))}"
        )


@cli.command()
def inspect(text: str):
    """Show how a title normalises — the fastest way to debug a bad match."""
    parsed = parse_title(text)
    typer.echo(f"raw       : {parsed.raw}")
    typer.echo(f"brand     : {parsed.brand}")
    typer.echo(f"tokens    : {parsed.tokens}")
    typer.echo(
        f"size      : {parsed.size.value} {parsed.size.unit} "
        f"-> {parsed.size.base_value} {parsed.size.base_unit} "
        f"(multipack x{parsed.size.multipack})"
    )
    typer.echo(f"match_key : {parsed.match_key}")

    with SessionLocal() as session:
        siblings = list(
            session.scalars(
                select(Offer).where(Offer.match_key == parsed.match_key).limit(20)
            )
        )
    typer.echo(f"\noffers sharing this key: {len(siblings)}")
    for offer in siblings:
        typer.echo(f"  [{offer.shop_id}] {offer.price_pln:>8.2f} PLN  {offer.title}")


@cli.command()
def basket(items: list[str]):
    """Optimise a basket. Pass product_id:qty pairs, e.g. `basket 12:2 44:1`."""
    wanted: dict[int, int] = {}
    for item in items:
        pid, _, qty = item.partition(":")
        wanted[int(pid)] = int(qty or 1)

    with SessionLocal() as session:
        result = optimize_basket(session, wanted)

    best, single, naive = result["best"], result["single_shop"], result["naive"]
    if not best:
        typer.secho("no offers found for that basket", fg="red")
        raise typer.Exit(code=1)

    typer.secho(f"\nOptimal split — {best.total_pln:.2f} PLN delivered", bold=True)
    for parcel in best.parcels:
        flag = " (est.)" if parcel.shipping_estimated and parcel.shipping_pln else ""
        typer.echo(
            f"\n  {parcel.shop_name}: {parcel.subtotal_pln:.2f} goods "
            f"+ {parcel.shipping_pln:.2f} shipping{flag} "
            f"= {parcel.total_pln:.2f} PLN, {parcel.min_days}-{parcel.max_days} d"
        )
        for line in parcel.items:
            typer.echo(f"      {line.quantity} x {line.offer_title[:58]:60} {line.line_total_pln:>8.2f}")
        for warning in parcel.warnings:
            typer.secho(f"      ! {warning}", fg="yellow")

    typer.echo(
        f"\n  vs cheapest single shop : {single.total_pln:.2f} PLN "
        f"(save {result['savings_vs_single_shop_pln']:.2f})"
        if single
        else ""
    )
    typer.echo(
        f"  vs 'cheapest price' pick: {naive.total_pln:.2f} PLN across "
        f"{len(naive.parcels)} parcels (save {result['savings_vs_naive_pln']:.2f})"
    )
    if result["missing_product_ids"]:
        typer.secho(
            f"  unavailable: {result['missing_product_ids']}", fg="yellow"
        )


if __name__ == "__main__":
    cli()
