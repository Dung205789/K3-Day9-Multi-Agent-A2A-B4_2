import os
import csv
import json

def generate_inputs():
    input_dir = "input"
    os.makedirs(input_dir, exist_ok=True)

    orders_path = os.path.join("data", "olist_orders_dataset.csv")
    if not os.path.exists(orders_path):
        print("data/olist_orders_dataset.csv not found!")
        return

    canceled_orders = []
    unavailable_orders = []
    delivered_orders = []
    all_orders = []

    with open(orders_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            oid = row["order_id"]
            all_orders.append(oid)
            status = row.get("order_status")
            if status == "canceled":
                canceled_orders.append(oid)
            elif status == "unavailable":
                unavailable_orders.append(oid)
            elif status == "delivered":
                delivered_orders.append(oid)

    sampled_order_ids = []
    sampled_order_ids.extend(canceled_orders)
    sampled_order_ids.extend(unavailable_orders)
    
    needed = 50 - len(sampled_order_ids)
    sampled_order_ids.extend(delivered_orders[:needed])

    if len(sampled_order_ids) < 50:
        remaining = [oid for oid in all_orders if oid not in sampled_order_ids]
        sampled_order_ids.extend(remaining[:50 - len(sampled_order_ids)])

    sampled_order_ids = sampled_order_ids[:50]

    for idx, order_id in enumerate(sampled_order_ids, start=1):
        case_id = f"EC_{idx:03d}"
        case_data = {
            "case_id": case_id,
            "opened_at": "2018-10-18T00:00:00-03:00",
            "customer_request": {
                "language": "vi",
                "message": "Đơn hàng của tôi có dấu hiệu khiếu nại. Hãy kiểm tra nguyên nhân và quyền lợi phù hợp.",
                "claimed_order_id": str(order_id)
            },
            "policy_version": "EC_POLICY_V1"
        }

        with open(os.path.join(input_dir, f"{case_id}.json"), "w", encoding="utf-8") as f:
            json.dump(case_data, f, indent=2, ensure_ascii=False)

    print(f"Generated exactly {len(sampled_order_ids)} sample inputs in '{input_dir}'.")

if __name__ == "__main__":
    generate_inputs()
