"""Build the 50 case files in input/.

The repo ships with an empty input/ directory, so this script selects real
Olist orders that exercise every branch of EC_POLICY_V1 and writes
EC_001.json .. EC_050.json. Selection is seeded, so re-running produces the
same 50 cases. If the official input set is dropped into input/ later, the
pipeline reads whatever is there - nothing else depends on this script.

    python -m src.make_inputs [--count 50] [--seed 20260804]
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import timedelta

from .config import INPUT_DIR
from .datastore import DataStore, parse_ts
from .policy import evaluate

# How many cases of each primary issue to include.
MIX = {
    "late_delivery_seller": 12,
    "late_delivery_logistics": 10,
    "canceled_order_paid": 8,
    "unavailable_order_paid": 6,
    "valid_split_payment": 8,
    "unsupported_late_claim": 6,
}

# Customer wording, written from the customer's point of view: they report a
# symptom, not a root cause. Several of these claims turn out to be wrong.
MESSAGES = {
    "late": [
        "Đơn hàng của tôi có dấu hiệu giao trễ. Hãy kiểm tra nguyên nhân và quyền lợi phù hợp.",
        "Tôi đặt hàng và nhận được muộn hơn ngày hẹn khá nhiều. Bên nào chịu trách nhiệm và tôi được bồi thường gì?",
        "Hàng về trễ so với cam kết trên đơn. Mong shop kiểm tra và xử lý phí vận chuyển cho tôi.",
        "Đơn này giao chậm hơn dự kiến làm tôi lỡ việc. Tôi muốn biết lỗi do người bán hay đơn vị giao hàng.",
        "Tôi theo dõi thấy ngày giao thực tế vượt quá hạn giao dự kiến. Đề nghị kiểm tra và hoàn phí ship.",
    ],
    "canceled": [
        "Đơn của tôi bị hủy nhưng tiền đã bị trừ. Tôi muốn được hoàn lại toàn bộ.",
        "Tôi thấy đơn chuyển sang trạng thái hủy trong khi thanh toán đã thành công. Xin xử lý hoàn tiền.",
        "Đơn hàng bị hủy mà chưa thấy hoàn tiền về tài khoản. Nhờ kiểm tra giúp tôi.",
    ],
    "unavailable": [
        "Hệ thống báo đơn không thực hiện được nhưng tôi đã thanh toán. Tôi cần hoàn tiền.",
        "Đơn của tôi ở trạng thái không khả dụng, tiền đã trừ. Xin kiểm tra và hoàn lại.",
        "Tôi đã trả tiền nhưng đơn không được xử lý tiếp. Mong bên bạn giải quyết khoản đã thanh toán.",
    ],
    "split": [
        "Tôi thấy tài khoản bị trừ tiền nhiều lần cho cùng một đơn. Có phải tôi bị thu trùng không?",
        "Đơn này hiện nhiều giao dịch thanh toán khác nhau. Nhờ kiểm tra xem tôi có bị tính dư không.",
        "Tôi bị ghi nợ hai lần cho một đơn hàng. Đề nghị đối soát lại giúp tôi.",
    ],
}


def _pick_message(issue: str, rng: random.Random) -> str:
    if issue in ("late_delivery_seller", "late_delivery_logistics", "unsupported_late_claim"):
        return rng.choice(MESSAGES["late"])
    if issue == "canceled_order_paid":
        return rng.choice(MESSAGES["canceled"])
    if issue == "unavailable_order_paid":
        return rng.choice(MESSAGES["unavailable"])
    return rng.choice(MESSAGES["split"])


def _opened_at(facts: dict, rng: random.Random) -> str:
    """A plausible ticket timestamp: shortly after the last known event."""
    anchor = (
        parse_ts(facts.get("delivered_ts"))
        or parse_ts(facts.get("carrier_ts"))
        or parse_ts(facts.get("purchase_ts"))
    )
    if anchor is None:
        return "2018-10-18T00:00:00-03:00"
    anchor += timedelta(days=rng.randint(1, 6), hours=rng.randint(0, 23))
    return anchor.strftime("%Y-%m-%dT%H:%M:%S-03:00")


def select(store: DataStore, mix: dict[str, int], seed: int) -> list[tuple[str, str]]:
    """Scan orders and pick (order_id, issue) pairs matching the requested mix."""
    rng = random.Random(seed)
    order_ids = list(store.orders)
    rng.shuffle(order_ids)

    buckets: dict[str, list[str]] = {k: [] for k in mix}
    need = dict(mix)
    for oid in order_ids:
        if not any(need.values()):
            break
        facts = store.order_facts(oid)
        if not facts.get("found") or facts["item_count"] == 0:
            continue
        if facts["payment_count"] == 0:
            continue
        res = evaluate(facts)
        issue = res["primary_issue"]
        if need.get(issue, 0) > 0 and not res["fallback_applied"]:
            # Keep split-payment cases genuinely multi-row and non-trivial.
            if issue == "valid_split_payment" and facts["payment_count"] < 2:
                continue
            buckets[issue].append(oid)
            need[issue] -= 1

    picked: list[tuple[str, str]] = []
    for issue, ids in buckets.items():
        picked.extend((oid, issue) for oid in ids)
    rng.shuffle(picked)
    return picked


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the 50 input cases")
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20260804)
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    args = ap.parse_args()

    existing = sorted(INPUT_DIR.glob("EC_*.json"))
    if existing and not args.force:
        print(f"input/ already has {len(existing)} case files - use --force to regenerate")
        return

    store = DataStore()
    scale = args.count / sum(MIX.values())
    mix = {k: max(1, round(v * scale)) for k, v in MIX.items()}
    # fix rounding drift
    while sum(mix.values()) > args.count:
        mix[max(mix, key=mix.get)] -= 1
    while sum(mix.values()) < args.count:
        mix[min(mix, key=mix.get)] += 1

    picked = select(store, mix, args.seed)
    rng = random.Random(args.seed)
    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    for n, (oid, issue) in enumerate(picked[: args.count], start=1):
        case_id = f"EC_{n:03d}"
        facts = store.order_facts(oid)
        case = {
            "case_id": case_id,
            "opened_at": _opened_at(facts, rng),
            "customer_request": {
                "language": "vi",
                "message": _pick_message(issue, rng),
                "claimed_order_id": oid,
            },
            "policy_version": "EC_POLICY_V1",
        }
        (INPUT_DIR / f"{case_id}.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        counts[issue] = counts.get(issue, 0) + 1

    print(f"wrote {min(len(picked), args.count)} case files to {INPUT_DIR}")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<26} {v}")


if __name__ == "__main__":
    main()
