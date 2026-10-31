"""Offline IEEE MAC-prefix lookup for FRITZ!Box Network Map."""
from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

_LOGGER = logging.getLogger(__name__)
_MAC_RE = re.compile(r"^[0-9A-F]{12}$")


class MacVendorDatabase:
    """Load a local CSV registry and resolve the longest matching prefix."""

    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path
        self.entries: dict[str, dict[str, str]] = {}
        self.loaded = False
        self.error: str | None = None
        self.load()

    def load(self) -> None:
        self.entries = {}
        self.loaded = False
        self.error = None
        if not self.csv_path.is_file():
            self.error = "Datei fehlt"
            _LOGGER.warning("MAC-Herstellerdatenbank nicht gefunden: %s", self.csv_path)
            return
        try:
            with self.csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    prefix = re.sub(r"[^0-9A-Fa-f]", "", str(row.get("prefix") or row.get("Assignment") or "")).upper()
                    vendor = str(row.get("vendor") or row.get("Organization Name") or "").strip()
                    registry = str(row.get("registry") or "").strip().upper()
                    if len(prefix) not in (6, 7, 9) or not re.fullmatch(r"[0-9A-F]+", prefix) or not vendor:
                        continue
                    if not registry:
                        registry = {6: "MA-L", 7: "MA-M", 9: "MA-S"}[len(prefix)]
                    # Prefer the most specific assignment if duplicate prefixes exist.
                    previous = self.entries.get(prefix)
                    if previous is None or len(prefix) > len(previous["prefix"]):
                        self.entries[prefix] = {"prefix": prefix, "vendor": vendor, "registry": registry}
            self.loaded = bool(self.entries)
            if not self.loaded:
                self.error = "Keine gültigen Einträge"
            _LOGGER.warning(
                "MAC-Herstellerdatenbank: geladen=%s, Einträge=%s, Datei=%s, Fehler=%s",
                self.loaded, len(self.entries), self.csv_path, self.error,
            )
        except (OSError, csv.Error, UnicodeError) as err:
            self.error = str(err)
            _LOGGER.warning("MAC-Herstellerdatenbank konnte nicht gelesen werden: %s", err, exc_info=True)

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def status(self) -> str:
        if self.loaded:
            return "Geladen"
        return f"Nicht verfügbar ({self.error or 'unbekannter Fehler'})"

    def lookup(self, mac: str | None) -> dict[str, str | None]:
        normalized = re.sub(r"[^0-9A-Fa-f]", "", str(mac or "")).upper()
        result: dict[str, str | None] = {
            "vendor": "Unbekannt", "mac_prefix": None, "vendor_registry": None,
            "vendor_lookup_status": "Datenbank nicht geladen" if not self.loaded else "Kein Treffer",
        }
        if not self.loaded or not _MAC_RE.fullmatch(normalized):
            return result
        # Locally administered MACs are often randomized/virtual and do not reliably
        # identify the device manufacturer. Keep the fact visible rather than guessing.
        first_octet = int(normalized[:2], 16)
        if first_octet & 0x02:
            result["vendor_lookup_status"] = "Lokal verwaltete MAC (Hersteller nicht ableitbar)"
            return result
        if first_octet & 0x01:
            result["vendor_lookup_status"] = "Multicast-MAC (kein Endgerät-Präfix)"
            return result
        for length in (9, 7, 6):
            prefix = normalized[:length]
            item = self.entries.get(prefix)
            if item:
                result.update({
                    "vendor": item["vendor"],
                    "mac_prefix": prefix,
                    "vendor_registry": item["registry"],
                    "vendor_lookup_status": "Treffer",
                })
                return result
        return result
