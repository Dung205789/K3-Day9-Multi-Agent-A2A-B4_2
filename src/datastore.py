"""Olist data access layer.

Loads the nine CSVs once, builds order-keyed indexes, and hands out *scoped*
views so that each agent can only touch the tables its role allows. The scope
boundary is what makes the handoffs meaningful: the Payment agent physically
cannot read delivery timestamps, so it has to ask for them.
"""
from __future__ import annotations

import threading
from datetime import datetime
from functools import lru_cache
from typing import Any, Iterable

import pandas as pd

from .config import DATA_DIR

TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_ts(value: Any) -> datetime | None:
    """Parse an Olist timestamp. Returns None for NaN/empty cells."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    for fmt in (TS_FORMAT, "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def money(value: float) -> float:
    """Round to 2 decimals the way the lab spec requires."""
    return round(float(value) + 1e-9, 2)


def _clean(record: dict) -> dict:
    """Replace pandas NaN with None so the dict is JSON-serialisable."""
    return {k: (None if pd.isna(v) else v) for k, v in record.items()}


class DataStore:
    """In-memory Olist warehouse with order-keyed indexes."""

    _instance: "DataStore | None" = None
    _lock = threading.Lock()

    def __init__(self, data_dir=DATA_DIR, with_geolocation: bool = False):
        self.data_dir = data_dir
        self.orders: dict[str, dict] = {}
        self.items: dict[str, list[dict]] = {}
        self.payments: dict[str, list[dict]] = {}
        self.reviews: dict[str, list[dict]] = {}
        self.customers: dict[str, dict] = {}
        self.sellers: dict[str, dict] = {}
        self.products: dict[str, dict] = {}
        self.category_en: dict[str, str] = {}
        self.geolocation: dict[str, dict] | None = None
        self._load(with_geolocation)

    # ------------------------------------------------------------------
    @classmethod
    def instance(cls) -> "DataStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = DataStore()
        return cls._instance

    def _read(self, name: str) -> pd.DataFrame:
        return pd.read_csv(self.data_dir / name, dtype=str, keep_default_na=True)

    def _load(self, with_geolocation: bool) -> None:
        orders = self._read("olist_orders_dataset.csv")
        for rec in orders.to_dict("records"):
            self.orders[rec["order_id"]] = _clean(rec)

        items = self._read("olist_order_items_dataset.csv")
        items["order_item_id"] = items["order_item_id"].astype(int)
        items["price"] = items["price"].astype(float)
        items["freight_value"] = items["freight_value"].astype(float)
        for rec in items.sort_values(["order_id", "order_item_id"]).to_dict("records"):
            self.items.setdefault(rec["order_id"], []).append(_clean(rec))

        payments = self._read("olist_order_payments_dataset.csv")
        payments["payment_sequential"] = payments["payment_sequential"].astype(int)
        payments["payment_installments"] = payments["payment_installments"].astype(int)
        payments["payment_value"] = payments["payment_value"].astype(float)
        sorted_pay = payments.sort_values(["order_id", "payment_sequential"])
        for rec in sorted_pay.to_dict("records"):
            self.payments.setdefault(rec["order_id"], []).append(_clean(rec))

        reviews = self._read("olist_order_reviews_dataset.csv")
        for rec in reviews.to_dict("records"):
            self.reviews.setdefault(rec["order_id"], []).append(_clean(rec))

        for rec in self._read("olist_customers_dataset.csv").to_dict("records"):
            self.customers[rec["customer_id"]] = _clean(rec)

        for rec in self._read("olist_sellers_dataset.csv").to_dict("records"):
            self.sellers[rec["seller_id"]] = _clean(rec)

        for rec in self._read("olist_products_dataset.csv").to_dict("records"):
            self.products[rec["product_id"]] = _clean(rec)

        trans = pd.read_csv(self.data_dir / "product_category_name_translation.csv")
        for rec in trans.to_dict("records"):
            self.category_en[rec["product_category_name"]] = rec[
                "product_category_name_english"
            ]

        if with_geolocation:
            self.load_geolocation()

    def load_geolocation(self) -> dict[str, dict]:
        """1M rows - only loaded when someone actually asks for a map."""
        if self.geolocation is None:
            geo = pd.read_csv(self.data_dir / "olist_geolocation_dataset.csv")
            grouped = geo.groupby("geolocation_zip_code_prefix").agg(
                lat=("geolocation_lat", "mean"),
                lng=("geolocation_lng", "mean"),
                city=("geolocation_city", "first"),
                state=("geolocation_state", "first"),
            )
            self.geolocation = {
                str(idx).zfill(5): _clean(row)
                for idx, row in grouped.to_dict("index").items()
            }
        return self.geolocation

    # ------------------------------------------------------------------
    # Raw accessors
    # ------------------------------------------------------------------
    def order(self, order_id: str) -> dict | None:
        return self.orders.get(order_id)

    def order_items(self, order_id: str) -> list[dict]:
        return self.items.get(order_id, [])

    def order_payments(self, order_id: str) -> list[dict]:
        return self.payments.get(order_id, [])

    def order_reviews(self, order_id: str) -> list[dict]:
        return self.reviews.get(order_id, [])

    def customer(self, customer_id: str) -> dict | None:
        return self.customers.get(customer_id)

    def seller(self, seller_id: str) -> dict | None:
        return self.sellers.get(seller_id)

    def product(self, product_id: str) -> dict | None:
        return self.products.get(product_id)

    def exists(self, kind: str, *parts: str) -> bool:
        """Existence check used by the Verifier agent to kill false positives."""
        try:
            if kind == "order":
                return parts[0] in self.orders
            if kind == "item":
                oid, iid = parts[0], str(parts[1])
                return any(str(i["order_item_id"]) == iid for i in self.order_items(oid))
            if kind == "payment":
                oid, seq = parts[0], str(parts[1])
                return any(
                    str(p["payment_sequential"]) == seq for p in self.order_payments(oid)
                )
            if kind == "seller":
                return parts[0] in self.sellers
        except (IndexError, KeyError):
            return False
        return False

    # ------------------------------------------------------------------
    # Derived facts (shared by agents and by the deterministic policy engine)
    # ------------------------------------------------------------------
    def order_facts(self, order_id: str) -> dict:
        """Everything a human CS agent would pull up on one screen."""
        order = self.order(order_id)
        if order is None:
            return {"order_id": order_id, "found": False}

        items = self.order_items(order_id)
        payments = self.order_payments(order_id)
        item_total = money(sum(i["price"] for i in items))
        freight_total = money(sum(i["freight_value"] for i in items))
        payment_total = money(sum(p["payment_value"] for p in payments))

        delivered = parse_ts(order.get("order_delivered_customer_date"))
        estimated = parse_ts(order.get("order_estimated_delivery_date"))
        carrier = parse_ts(order.get("order_delivered_carrier_date"))

        late_sellers: list[str] = []
        late_item_ids: list[str] = []
        for item in items:
            limit = parse_ts(item.get("shipping_limit_date"))
            if carrier and limit and carrier > limit:
                late_item_ids.append(f"{order_id}:{item['order_item_id']}")
                if item["seller_id"] not in late_sellers:
                    late_sellers.append(item["seller_id"])

        expected_total = money(item_total + freight_total)
        return {
            "order_id": order_id,
            "found": True,
            "order_status": order.get("order_status"),
            "customer_id": order.get("customer_id"),
            "purchase_ts": order.get("order_purchase_timestamp"),
            "approved_ts": order.get("order_approved_at"),
            "carrier_ts": order.get("order_delivered_carrier_date"),
            "delivered_ts": order.get("order_delivered_customer_date"),
            "estimated_ts": order.get("order_estimated_delivery_date"),
            "item_count": len(items),
            "payment_count": len(payments),
            "seller_ids": list(dict.fromkeys(i["seller_id"] for i in items)),
            "item_total_brl": item_total,
            "freight_total_brl": freight_total,
            "payment_total_brl": payment_total,
            "expected_total_brl": expected_total,
            "payment_gap_brl": money(payment_total - expected_total),
            "payment_matches": abs(payment_total - expected_total) <= 0.10,
            "delivered_after_estimate": bool(
                delivered and estimated and delivered > estimated
            ),
            "delivery_delay_days": (
                round((delivered - estimated).total_seconds() / 86400, 2)
                if delivered and estimated
                else None
            ),
            "carrier_after_shipping_limit": bool(late_sellers),
            "late_seller_ids": late_sellers,
            "late_item_ids": late_item_ids,
            "items": items,
            "payments": payments,
        }


# ----------------------------------------------------------------------
# Scoped views - each agent gets one of these, not the DataStore itself.
# ----------------------------------------------------------------------
class ScopedView:
    """A read-only window onto the warehouse, limited to named tables."""

    def __init__(self, store: DataStore, agent: str, tables: Iterable[str]):
        self._store = store
        self.agent = agent
        self.tables = tuple(tables)
        self.reads: list[str] = []

    def _guard(self, table: str) -> None:
        if table not in self.tables:
            raise PermissionError(
                f"agent '{self.agent}' is not allowed to read table '{table}' "
                f"(scope: {', '.join(self.tables) or 'none'})"
            )
        self.reads.append(table)

    def order(self, order_id: str) -> dict | None:
        self._guard("orders")
        return self._store.order(order_id)

    def items(self, order_id: str) -> list[dict]:
        self._guard("order_items")
        return self._store.order_items(order_id)

    def payments(self, order_id: str) -> list[dict]:
        self._guard("order_payments")
        return self._store.order_payments(order_id)

    def reviews(self, order_id: str) -> list[dict]:
        self._guard("order_reviews")
        return self._store.order_reviews(order_id)

    def seller(self, seller_id: str) -> dict | None:
        self._guard("sellers")
        return self._store.seller(seller_id)

    def product(self, product_id: str) -> dict | None:
        self._guard("products")
        return self._store.product(product_id)

    def customer(self, customer_id: str) -> dict | None:
        self._guard("customers")
        return self._store.customer(customer_id)

    def exists(self, kind: str, *parts: str) -> bool:
        self._guard("__existence__")
        return self._store.exists(kind, *parts)


# agent -> tables it may read. Mirrored in architecture.md.
AGENT_SCOPES: dict[str, tuple[str, ...]] = {
    "coordinator": (),
    "order_seller": ("orders", "order_items", "sellers", "products"),
    "payment": ("order_payments", "order_items"),
    "delivery": ("orders", "order_items"),
    "policy": (),
    "verifier": ("__existence__",),
}


def scoped(store: DataStore, agent: str) -> ScopedView:
    return ScopedView(store, agent, AGENT_SCOPES.get(agent, ()))


@lru_cache(maxsize=1)
def get_store() -> DataStore:
    return DataStore.instance()
