"""Compare EDGAR information tables in filing order, including amendments."""

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


def read_rows(path):
    source = Path(path).read_text(encoding="utf-8-sig")
    if source.lstrip().startswith("<"):
        root = ET.fromstring(source)
        for row in root.findall(".//{*}infoTable"):
            def get(key):
                return row.findtext(key, default="").strip()

            yield (
                get("{*}nameOfIssuer"), get("{*}titleOfClass"), get("{*}cusip"),
                get("{*}value"), get("{*}shrsOrPrnAmt/{*}sshPrnamt"),
                get("{*}shrsOrPrnAmt/{*}sshPrnamtType"), get("{*}putCall"),
            )
    else:
        # Accept the pipe-delimited rows in a text capture of the SEC rendered table.
        for line in source.splitlines():
            cells = re.sub(r"^L\d+:\s*", "", line).split("|")
            cells = [cell.strip() for cell in cells]
            if len(cells) >= 8 and re.fullmatch(r"[A-Z0-9*@#]{9}", cells[2]):
                name, security_class, cusip, _, value, quantity, units, option = cells[:8]
                yield name, security_class, cusip, value, quantity, units, option


def compile_period(specs, multiplier):
    positions = {}
    filings = []
    for operation, path in specs:
        rows = list(read_rows(path))
        if not rows:
            raise ValueError(f"No holdings rows in {path}")
        if operation == "base" or operation == "restatement":
            positions.clear()
        total = 0
        for name, security_class, cusip, value, quantity, units, option in rows:
            if not all((name, cusip, security_class)) or units.upper() not in {"SH", "PRN"}:
                raise ValueError(f"Malformed holding in {path}: {name} {cusip} {units}")
            value = int(value.replace(",", "")) * multiplier
            quantity = int(quantity.replace(",", ""))
            key = (cusip.upper(), " ".join(security_class.upper().split()), units.upper(), option.upper())
            position = positions.setdefault(key, {"name": name, "quantity": 0, "value": 0})
            position["quantity"] += quantity
            position["value"] += value
            total += value
        filings.append({"type": operation, "rows": len(rows), "value_usd": total})
    return positions, filings


def period(args, label):
    amendments = getattr(args, f"{label}_amendment")
    return compile_period(
        [("base", getattr(args, label)), *amendments],
        getattr(args, f"{label}_value_multiplier"),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for label in ("previous", "current"):
        parser.add_argument(f"--{label}", required=True, help="EDGAR XML or pipe-delimited SEC table capture")
        parser.add_argument(f"--{label}-amendment", nargs=2, action="append", default=[],
                            metavar=("TYPE", "FILE"), help="addition or restatement, in filing order")
        parser.add_argument(f"--{label}-value-multiplier", type=int, choices=(1, 1000), default=1,
                            help="Use 1000 only if the filing explicitly reports value in thousands")
    args = parser.parse_args()
    for amendments in (args.previous_amendment, args.current_amendment):
        if any(kind not in {"addition", "restatement"} for kind, _ in amendments):
            parser.error("amendment TYPE must be addition or restatement")
    previous, previous_filings = period(args, "previous")
    current, current_filings = period(args, "current")
    changes = []
    counts = defaultdict(int)
    for key in sorted(previous.keys() | current.keys()):
        old, new = previous.get(key), current.get(key)
        delta = (new or {}).get("quantity", 0) - (old or {}).get("quantity", 0)
        if old is None:
            status = "new"
        elif new is None:
            status = "absent"
        else:
            status = "increased" if delta > 0 else "decreased" if delta < 0 else "unchanged"
        counts[status] += 1
        changes.append(dict(zip(("cusip", "class", "units", "option"), key)) | {
            "issuer": (new or old)["name"], "previous": old, "current": new,
            "quantity_change": delta, "status": status,
        })
    print(json.dumps({
        "previous_filings": previous_filings,
        "current_filings": current_filings,
        "previous_value_usd": sum(row["value"] for row in previous.values()),
        "current_value_usd": sum(row["value"] for row in current.values()),
        "counts": dict(counts),
        "holdings": changes,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
