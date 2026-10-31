"""User-editable device type and role overrides."""
from __future__ import annotations
import csv
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

class DeviceOverrideDatabase:
    """Load manually confirmed device classifications from a local CSV."""
    FIELDS = ("mac", "hostname", "model", "manufacturer", "device_type", "device_role", "notes")

    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path
        self.entries: list[dict[str, str]] = []
        self.error: str | None = None
        self.load()

    def load(self) -> None:
        self.entries = []
        self.error = None
        if not self.csv_path.is_file():
            self.error = "Datei fehlt"
            _LOGGER.warning("Gerätezuordnungsdatei nicht gefunden: %s", self.csv_path)
            return
        try:
            with self.csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    entry = {field: str(row.get(field) or "").strip() for field in self.FIELDS}
                    entry["mac"] = entry["mac"].replace("-", ":").upper()
                    if not any(entry.values()):
                        continue
                    if entry["mac"] and not _valid_mac(entry["mac"]):
                        _LOGGER.warning("Ungültige MAC in device_overrides.csv übersprungen: %s", entry["mac"])
                        continue
                    if not any(entry.get(key) for key in ("mac", "hostname", "model")):
                        _LOGGER.warning("Gerätezuordnung ohne MAC, Hostname oder Modell übersprungen.")
                        continue
                    self.entries.append(entry)
        except (OSError, csv.Error, UnicodeError) as err:
            self.error = str(err)
            _LOGGER.warning("Gerätezuordnungen konnten nicht gelesen werden: %s", err, exc_info=True)
        _LOGGER.warning("GERÄTEZUORDNUNGEN: geladen=%s, Einträge=%s, Datei=%s, Fehler=%s",
                        self.loaded, self.count, self.csv_path, self.error)

    @property
    def loaded(self) -> bool:
        return self.error is None and self.csv_path.is_file()

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def status(self) -> str:
        if self.error:
            return f"Nicht verfügbar ({self.error})"
        return "Geladen" if self.loaded else "Nicht verfügbar"

    def lookup(self, device: dict) -> dict[str, str | None]:
        mac = str(device.get("mac") or "").strip().replace("-", ":").upper()
        names = {str(device.get(key) or "").strip().casefold()
                 for key in ("friendly_name", "name") if str(device.get(key) or "").strip()}
        model = str(device.get("model") or "").strip().casefold()
        for entry in self.entries:
            if entry["mac"] and entry["mac"] == mac:
                return _as_result(entry, "MAC")
        for entry in self.entries:
            if entry["hostname"] and entry["hostname"].casefold() in names:
                return _as_result(entry, "Hostname")
        for entry in self.entries:
            if entry["model"] and model and entry["model"].casefold() == model:
                return _as_result(entry, "Modell")
        return {"override_model": None, "override_manufacturer": None, "override_device_type": None,
                "override_device_role": None, "override_match": "Keine manuelle Zuordnung",
                "override_notes": None}

def _as_result(entry: dict[str, str], match: str) -> dict[str, str | None]:
    return {"override_model": entry["model"] or None,
            "override_manufacturer": entry["manufacturer"] or None,
            "override_device_type": entry["device_type"] or None,
            "override_device_role": entry["device_role"] or None,
            "override_match": f"Treffer über {match}",
            "override_notes": entry["notes"] or None}

def _valid_mac(value: str) -> bool:
    parts = value.split(":")
    return len(parts) == 6 and all(len(part) == 2 and all(c in "0123456789ABCDEF" for c in part)
                                   for part in parts)
