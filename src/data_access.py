"""Loads the Olist CSVs once and exposes indexed, per-order lookups.

Only the tables referenced by EC_POLICY_V1 (orders, order_items,
order_payments, sellers) are loaded — geolocation/products/reviews are not
needed by any business rule in README.md.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@functools.lru_cache(maxsize=1)
def _orders() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "olist_orders_dataset.csv", dtype=str).set_index(
        "order_id", drop=False
    )


@functools.lru_cache(maxsize=1)
def _items() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "olist_order_items_dataset.csv", dtype=str)
    df["price"] = df["price"].astype(float)
    df["freight_value"] = df["freight_value"].astype(float)
    return df


@functools.lru_cache(maxsize=1)
def _payments() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "olist_order_payments_dataset.csv", dtype=str)
    df["payment_value"] = df["payment_value"].astype(float)
    return df


@functools.lru_cache(maxsize=1)
def _sellers() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "olist_sellers_dataset.csv", dtype=str).set_index(
        "seller_id", drop=False
    )


def get_order(order_id: str) -> dict | None:
    df = _orders()
    if order_id not in df.index:
        return None
    row = df.loc[order_id]
    return row.to_dict()


def get_items(order_id: str) -> list[dict]:
    df = _items()
    rows = df[df["order_id"] == order_id]
    rows = rows.sort_values("order_item_id", key=lambda s: s.astype(int))
    return rows.to_dict(orient="records")


def get_payments(order_id: str) -> list[dict]:
    df = _payments()
    rows = df[df["order_id"] == order_id]
    rows = rows.sort_values("payment_sequential", key=lambda s: s.astype(int))
    return rows.to_dict(orient="records")


def get_seller(seller_id: str) -> dict | None:
    df = _sellers()
    if seller_id not in df.index:
        return None
    row = df.loc[seller_id]
    return row.to_dict()


def order_exists(order_id: str) -> bool:
    return order_id in _orders().index
