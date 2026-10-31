#!/usr/bin/env python3
"""Download public IEEE MAC registries into mac_vendors.csv (stdlib only)."""
from __future__ import annotations
import csv
import re
import sys
import urllib.request
from pathlib import Path

SOURCES = {
    "MA-L": "https://standards-oui.ieee.org/oui/oui.csv",
    "MA-M": "https://standards-oui.ieee.org/oui28/mam.csv",
    "MA-S": "https://standards-oui.ieee.org/oui36/oui36.csv",
}
OUT = Path(__file__).resolve().parent / "mac_vendors.csv"


def main() -> int:
    records: dict[tuple[str, str], dict[str, str]] = {}
    for registry, url in SOURCES.items():
        print(f"Lade {registry}: {url}")
        request = urllib.request.Request(url, headers={"User-Agent": "FRITZBox-Network-Map/0.2"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                content = response.read().decode("utf-8-sig")
        except Exception as err:
            print(f"FEHLER: {registry}: {err}", file=sys.stderr)
            return 1
        reader = csv.DictReader(content.splitlines())
        found = 0
        for row in reader:
            assignment = re.sub(r"[^0-9A-Fa-f]", "", str(row.get("Assignment") or "")).upper()
            vendor = str(row.get("Organization Name") or "").strip()
            if len(assignment) not in (6, 7, 9) or not re.fullmatch(r"[0-9A-F]+", assignment) or not vendor:
                continue
            records[(assignment, registry)] = {"prefix": assignment, "vendor": vendor, "registry": registry}
            found += 1
        if found < 50:
            print(f"FEHLER: {registry}: nur {found} gültige Einträge; Datei nicht geschrieben.", file=sys.stderr)
            return 1
        print(f"  {found:,} Einträge")
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["prefix", "vendor", "registry"])
        writer.writeheader()
        writer.writerows(sorted(records.values(), key=lambda item: (item["prefix"], item["registry"])))
    print(f"Fertig: {len(records):,} Zuordnungen in {OUT}")
    print("Hinweis: Eine Herstellerzuordnung beweist nicht, dass ein Gerät ein Switch ist.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
