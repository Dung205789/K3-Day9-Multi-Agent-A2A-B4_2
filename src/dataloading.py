import os
import pandas as pd
from typing import List, Dict, Any, Optional, Set
from src.config import DATA_DIR

class OlistDatabase:
    """Singleton memory cache for Olist CSV Dataframes to ensure lightning-fast agent queries

    without reloading from disk on each step, while guaranteeing verifiable evidence lookups.
    """
    _instance = None

    def __new__(cls, data_dir: str = DATA_DIR):
        if cls._instance is None:
            cls._instance = super(OlistDatabase, cls).__new__(cls)
            cls._instance.data_dir = data_dir
            cls._instance._load_datasets()
        return cls._instance

    def _load_datasets(self):
        """Loads all critical CSV datasets into memory indexed by key IDs."""
        print(f"[OlistDatabase] Initializing memory cache from: {self.data_dir}")
        orders_path = os.path.join(self.data_dir, "olist_orders_dataset.csv")
        items_path = os.path.join(self.data_dir, "olist_order_items_dataset.csv")
        payments_path = os.path.join(self.data_dir, "olist_order_payments_dataset.csv")
        sellers_path = os.path.join(self.data_dir, "olist_sellers_dataset.csv")

        self.orders_df = pd.read_csv(orders_path)
        self.items_df = pd.read_csv(items_path)
        self.payments_df = pd.read_csv(payments_path)
        self.sellers_df = pd.read_csv(sellers_path)

        # Create quick-lookup sets for Verifier Agent Hard Gate checks
        self.valid_order_ids: Set[str] = set(self.orders_df['order_id'].astype(str))
        
        # Build set of item evidence identifiers: "item:<order_id>:<order_item_id>"
        item_keys = self.items_df['order_id'].astype(str) + ":" + self.items_df['order_item_id'].astype(str)
        self.valid_item_keys: Set[str] = set("item:" + item_keys)

        # Build set of payment evidence identifiers: "payment:<order_id>:<payment_sequential>"
        payment_keys = self.payments_df['order_id'].astype(str) + ":" + self.payments_df['payment_sequential'].astype(str)
        self.valid_payment_keys: Set[str] = set("payment:" + payment_keys)

        self.valid_seller_ids: Set[str] = set(self.sellers_df['seller_id'].astype(str))

        # Valid policy root cause codes defined in Section 4 of README
        self.valid_policy_codes: Set[str] = {
            "SELLER_HANDOFF_AFTER_LIMIT",
            "CARRIER_DELIVERED_AFTER_ESTIMATE",
            "ORDER_CANCELED_AFTER_PAYMENT",
            "ORDER_UNAVAILABLE_AFTER_PAYMENT",
            "MULTIPLE_PAYMENTS_RECONCILED",
            "DELIVERY_WITHIN_ESTIMATE"
        }
        print("[OlistDatabase] Data loading complete and indexes initialized successfully.")

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        rows = self.orders_df[self.orders_df['order_id'] == order_id]
        if rows.empty:
            return None
        return rows.iloc[0].where(pd.notnull(rows.iloc[0]), None).to_dict()

    def get_order_items(self, order_id: str) -> List[Dict[str, Any]]:
        rows = self.items_df[self.items_df['order_id'] == order_id]
        return [r.where(pd.notnull(r), None).to_dict() for _, r in rows.iterrows()]

    def get_order_payments(self, order_id: str) -> List[Dict[str, Any]]:
        rows = self.payments_df[self.payments_df['order_id'] == order_id]
        return [r.where(pd.notnull(r), None).to_dict() for _, r in rows.iterrows()]

    def check_evidence_exists(self, evidence_id: str) -> bool:
        """Verifier Agent check: returns True if and only if the evidence_id exists in the raw CSV dataset."""
        if not evidence_id or not isinstance(evidence_id, str):
            return False
        
        parts = evidence_id.split(":", 1)
        if len(parts) != 2:
            return False
        
        prefix = parts[0]
        remainder = parts[1]
        
        if prefix == "order":
            return remainder in self.valid_order_ids
        elif prefix == "item":
            return evidence_id in self.valid_item_keys
        elif prefix == "payment":
            return evidence_id in self.valid_payment_keys
        elif prefix == "seller":
            return remainder in self.valid_seller_ids
        elif prefix == "policy":
            return remainder in self.valid_policy_codes
        
        return False

# Convenience global accessor
def get_db() -> OlistDatabase:
    return OlistDatabase()
