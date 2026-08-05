"""Zip output/ for submission - and refuse to build a zip that would be rejected.

README section 8: the zip must contain exactly EC_001.json .. EC_050.json and
nothing else. This script checks that before writing, so a missing case or a
stray file fails here instead of at grading time.

    python -m src.package_submission
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from .config import OUTPUT_DIR, ROOT

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    ap = argparse.ArgumentParser(description="Package output/ into a submission zip")
    ap.add_argument("--out", type=Path, default=ROOT / "submission.zip")
    ap.add_argument("--expect", type=int, default=50)
    ap.add_argument(
        "--prefix",
        default="",
        help="folder prefix inside the zip, e.g. 'output' to get output/EC_001.json. "
             "Default is flat: EC_001.json at the zip root.",
    )
    args = ap.parse_args()

    files = sorted(OUTPUT_DIR.glob("*"))
    problems: list[str] = []

    json_files = [f for f in files if f.suffix == ".json" and f.stem.startswith("EC_")]
    strays = [f.name for f in files if f not in json_files and f.name != ".gitkeep"]
    if strays:
        problems.append(f"file lạ trong output/: {strays}")

    expected = {f"EC_{i:03d}" for i in range(1, args.expect + 1)}
    got = {f.stem for f in json_files}
    if missing := sorted(expected - got):
        problems.append(f"thiếu {len(missing)} case: {missing[:5]}…")
    if extra := sorted(got - expected):
        problems.append(f"thừa case ngoài dải EC_001..EC_{args.expect:03d}: {extra[:5]}")

    for f in json_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{f.name}: JSON hỏng ({exc})")
            continue
        if data.get("case_id") != f.stem:
            problems.append(f"{f.name}: case_id={data.get('case_id')} không khớp tên file")

    if problems:
        print("KHÔNG đóng gói được:")
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(1)

    prefix = args.prefix.strip("/")
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(json_files):
            zf.write(f, arcname=f"{prefix}/{f.name}" if prefix else f.name)

    # Read the archive back rather than trusting what we just wrote.
    with zipfile.ZipFile(args.out) as zf:
        names = zf.namelist()
        if bad := zf.testzip():
            print(f"KHÔNG đóng gói được: archive hỏng tại {bad}")
            sys.exit(1)
        for name in names:
            data = json.loads(zf.read(name).decode("utf-8"))
            stem = name.rsplit("/", 1)[-1].removesuffix(".json")
            if data["case_id"] != stem:
                print(f"KHÔNG đóng gói được: {name} có case_id={data['case_id']}")
                sys.exit(1)

    size_kb = args.out.stat().st_size / 1024
    print(f"✓ {args.out.name}: {len(names)} entry, {size_kb:.1f} KB")
    print(f"  cấu trúc: {names[0]} … {names[-1]}")
    print("  đã đọc lại từ archive: mọi file parse được, case_id khớp tên file.")
    print("  zip chỉ chứa output JSON - không có source, .env hay file audit.")


if __name__ == "__main__":
    main()
