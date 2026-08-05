import os
import csv
from typing import Dict, List, Optional

class DataLoader:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.orders: Dict[str, dict] = {}
        self.order_items: Dict[str, List[dict]] = {}
        self.order_payments: Dict[str, List[dict]] = {}
        self.sellers: Dict[str, dict] = {}
        self.products: Dict[str, dict] = {}
        self._load_data()

    def _load_data(self):
        # Load orders
        orders_path = os.path.join(self.data_dir, "olist_orders_dataset.csv")
        if os.path.exists(orders_path):
            with open(orders_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    oid = str(row["order_id"])
                    # convert empty strings to None
                    clean_row = {k: (v if v != "" else None) for k, v in row.items()}
                    self.orders[oid] = clean_row

        # Load order items
        items_path = os.path.join(self.data_dir, "olist_order_items_dataset.csv")
        if os.path.exists(items_path):
            with open(items_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    oid = str(row["order_id"])
                    clean_row = {k: (v if v != "" else None) for k, v in row.items()}
                    if oid not in self.order_items:
                        self.order_items[oid] = []
                    self.order_items[oid].append(clean_row)

        # Load order payments
        payments_path = os.path.join(self.data_dir, "olist_order_payments_dataset.csv")
        if os.path.exists(payments_path):
            with open(payments_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    oid = str(row["order_id"])
                    clean_row = {k: (v if v != "" else None) for k, v in row.items()}
                    if oid not in self.order_payments:
                        self.order_payments[oid] = []
                    self.order_payments[oid].append(clean_row)

        # Load sellers
        sellers_path = os.path.join(self.data_dir, "olist_sellers_dataset.csv")
        if os.path.exists(sellers_path):
            with open(sellers_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sid = str(row["seller_id"])
                    clean_row = {k: (v if v != "" else None) for k, v in row.items()}
                    self.sellers[sid] = clean_row

        # Load products
        products_path = os.path.join(self.data_dir, "olist_products_dataset.csv")
        if os.path.exists(products_path):
            with open(products_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pid = str(row["product_id"])
                    clean_row = {k: (v if v != "" else None) for k, v in row.items()}
                    self.products[pid] = clean_row

    def get_order(self, order_id: str) -> Optional[dict]:
        return self.orders.get(order_id)

    def get_order_items(self, order_id: str) -> List[dict]:
        items = self.order_items.get(order_id, [])
        return sorted(items, key=lambda x: int(x.get("order_item_id") or 1))

    def get_order_payments(self, order_id: str) -> List[dict]:
        payments = self.order_payments.get(order_id, [])
        return sorted(payments, key=lambda x: int(x.get("payment_sequential") or 1))

    def get_seller(self, seller_id: str) -> Optional[dict]:
        return self.sellers.get(seller_id)
