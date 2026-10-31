from __future__ import annotations

import logging
import re

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up and dynamically synchronize per-device sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities_by_mac: dict[str, list[FritzBoxDeviceSensor]] = {}
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    def make_entities(device: dict) -> list[FritzBoxDeviceSensor]:
        mac = str(device.get("mac", "")).strip().upper()
        if not mac:
            return []
        return [
            FritzBoxDeviceSensor(coordinator, entry, mac, "speed_mbps", "Datenrate", "mdi:speedometer", "Mbit/s"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "ipv4", "IPv4-Adresse", "mdi:ip-network"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "ipv6", "IPv6-Adresse", "mdi:ip-network"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "status", "Status", "mdi:lan-connect"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "connection_type", "Verbindungstyp", "mdi:lan"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "direct_connection", "Direkt verbunden mit", "mdi:lan-connect"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "switch_port", "Switch-Port", "mdi:ethernet"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "switch_name", "Switch", "mdi:switch"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_2_4_speed_mbps", "WLAN 2,4 GHz Datenrate", "mdi:speedometer", "Mbit/s"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_2_4_channel", "WLAN 2,4 GHz Kanal", "mdi:wifi"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_2_4_signal_rx_dbm", "WLAN 2,4 GHz Empfangssignal", "mdi:signal", "dBm"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_2_4_signal_tx_dbm", "WLAN 2,4 GHz Sendesignal", "mdi:signal", "dBm"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_2_4_channel_width", "WLAN 2,4 GHz Kanalbreite", "mdi:arrow-expand-horizontal", "MHz"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_2_4_guest", "WLAN 2,4 GHz Gastnetz", "mdi:account-multiple"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_5_speed_mbps", "WLAN 5 GHz Datenrate", "mdi:speedometer", "Mbit/s"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_5_channel", "WLAN 5 GHz Kanal", "mdi:wifi"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_5_signal_rx_dbm", "WLAN 5 GHz Empfangssignal", "mdi:signal", "dBm"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_5_signal_tx_dbm", "WLAN 5 GHz Sendesignal", "mdi:signal", "dBm"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_5_channel_width", "WLAN 5 GHz Kanalbreite", "mdi:arrow-expand-horizontal", "MHz"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "wifi_5_guest", "WLAN 5 GHz Gastnetz", "mdi:account-multiple"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "device_role", "Geräterolle", "mdi:router-network"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "mac_address", "MAC-Adresse", "mdi:barcode"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "vendor", "Hersteller", "mdi:factory"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "mac_prefix", "MAC-Präfix", "mdi:barcode-scan"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "vendor_registry", "Hersteller-Registrierung", "mdi:database-search"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "vendor_lookup_status", "Hersteller-Erkennung", "mdi:check-network"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "device_type_detection", "Gerätetyp-Erkennung", "mdi:devices"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "device_type", "Gerätetyp", "mdi:network-outline"),
            FritzBoxDeviceSensor(coordinator, entry, mac, "model", "Modell", "mdi:tag-text"),
        ]

    @callback
    def handle_update() -> None:
        """Add sensors for new MACs and schedule cleanup for disappeared MACs."""
        devices = coordinator.data
        # The coordinator only updates data after a successful fetch. Also avoid
        # treating an unexpectedly empty response as proof that every device vanished.
        if not isinstance(devices, list) or not devices:
            _LOGGER.warning(
                "Gerätesynchronisierung übersprungen: FRITZ!Box-Liste ist leer oder ungültig."
            )
            return

        current_by_mac = {
            str(device.get("mac", "")).strip().upper(): device
            for device in devices
            if isinstance(device, dict) and str(device.get("mac", "")).strip()
        }
        current_macs = set(current_by_mac)
        known_macs = set(entities_by_mac)

        # Clean up old entity-registry entries left by earlier integration versions.
        # Only touch entities belonging to this config entry and this sensor platform.
        for registry_entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
            prefix = f"{entry.entry_id}_"
            if not registry_entity.unique_id.startswith(prefix):
                continue
            suffix = registry_entity.unique_id[len(prefix):]
            # Unique IDs use <mac_with_underscores>_<field>; the last suffix is
            # one of the known field names, so reconstruct the MAC without guessing.
            field_suffixes = ("_type_detection", "_device_type", "_model", "_vendor_status", "_wifi24_signal_rx", "_wifi24_signal_tx", "_wifi24_channel", "_wifi24_signal", "_wifi24_speed", "_wifi24_width", "_wifi24_guest", "_wifi5_signal_rx", "_wifi5_signal_tx", "_wifi5_channel", "_wifi5_signal", "_wifi5_speed", "_wifi5_width", "_wifi5_guest", "_registry", "_prefix", "_vendor", "_wifi_speed", "_direct_connection", "_connection", "_ipv4", "_ipv6", "_status", "_speed", "_channel", "_signal", "_role", "_mac")
            mac_part = next((suffix[:-len(field)] for field in field_suffixes if suffix.endswith(field)), None)
            if mac_part is None:
                continue
            mac = mac_part.replace("_", ":").upper()
            # These legacy sensors duplicated the explicit RX/TX dBm sensors.
            # Remove them even when the device itself is still present; otherwise
            # Home Assistant keeps the old entity in the registry indefinitely.
            obsolete_fields = ("_wifi24_signal", "_wifi5_signal", "_signal")
            is_obsolete_signal_sensor = any(suffix.endswith(field) for field in obsolete_fields)
            valid_mac = bool(re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac))
            if valid_mac and (mac not in current_macs or is_obsolete_signal_sensor):
                entity_registry.async_remove(registry_entity.entity_id)
                _LOGGER.info(
                    "Veraltete Entität entfernt: %s (MAC %s, Feld %s)",
                    registry_entity.entity_id,
                    mac,
                    next((field for field in obsolete_fields if suffix.endswith(field)), "Gerät nicht mehr vorhanden"),
                )

        # Remove stale integration device entries after their stale entities are gone.
        for registry_device in list(device_registry.devices.values()):
            if entry.entry_id not in registry_device.config_entries:
                continue
            macs = {
                identifier[1].upper()
                for identifier in registry_device.identifiers
                if isinstance(identifier, tuple) and len(identifier) == 2 and identifier[0] == DOMAIN
            }
            if macs and not (macs & current_macs):
                try:
                    device_registry.async_remove_device(registry_device.id)
                    _LOGGER.info("Veraltetes Gerät entfernt: %s", ", ".join(sorted(macs)))
                except (KeyError, ValueError) as err:
                    _LOGGER.warning("Veraltetes Gerät konnte nicht entfernt werden: %s", err)

        new_entities: list[FritzBoxDeviceSensor] = []
        for mac in current_macs - known_macs:
            created = make_entities(current_by_mac[mac])
            if created:
                entities_by_mac[mac] = created
                new_entities.extend(created)
        if new_entities:
            async_add_entities(new_entities)
            _LOGGER.info("Neue Geräte aufgenommen: %s", len(new_entities) // 28)

        removed_macs = known_macs - current_macs
        if removed_macs:
            hass.async_create_task(remove_missing_devices(removed_macs))

    async def remove_missing_devices(removed_macs: set[str]) -> None:
        for mac in removed_macs:
            entities = entities_by_mac.get(mac, [])
            # Remove the entities from the platform and entity registry.
            for entity in entities:
                if entity.entity_id:
                    await entity.async_remove(force_remove=True)
            entities_by_mac.pop(mac, None)

            # Remove the matching integration device only after its entities are gone.
            registry_device = device_registry.async_get_device(identifiers={(DOMAIN, mac)})
            if registry_device and entry.entry_id in registry_device.config_entries:
                try:
                    device_registry.async_remove_device(registry_device.id)
                except (KeyError, ValueError) as err:
                    _LOGGER.warning("Gerät %s konnte nicht aus der Geräteverwaltung entfernt werden: %s", mac, err)
            _LOGGER.info("Nicht mehr vorhandenes Gerät entfernt: %s", mac)

    # Initial set-up: create sensors for all currently known devices.
    initial_entities: list[FritzBoxDeviceSensor] = []
    for device in coordinator.data or []:
        if not isinstance(device, dict):
            continue
        mac = str(device.get("mac", "")).strip().upper()
        if not mac or mac in entities_by_mac:
            continue
        created = make_entities(device)
        if created:
            entities_by_mac[mac] = created
            initial_entities.extend(created)
    async_add_entities(initial_entities + [
        NetworkTopologySensor(coordinator, entry),
        MacDatabaseDiagnosticSensor(coordinator, entry, "status"),
        MacDatabaseDiagnosticSensor(coordinator, entry, "entries"),
        OverrideDatabaseDiagnosticSensor(coordinator, entry, "status"),
        OverrideDatabaseDiagnosticSensor(coordinator, entry, "entries"),
        SwitchSNMPDiagnosticSensor(coordinator, entry),
    ])

    coordinator.async_add_listener(handle_update)
    # Run cleanup immediately on startup; waiting for the next coordinator poll
    # would leave obsolete registry entities visible after a restart.
    handle_update()


class FritzBoxDeviceSensor(CoordinatorEntity, SensorEntity):
    """A sensor for one property of a FRITZ!Box network device."""

    def __init__(self, coordinator, entry: ConfigEntry, mac: str, field: str, label: str, icon: str, unit: str | None = None):
        super().__init__(coordinator)
        self._mac = mac
        self._field = field
        self._label = label
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_has_entity_name = True
        self._attr_name = label
        unique_mac = self._mac.replace(":", "_").lower()

        unique_fields = {
            "speed_mbps": "speed",
            "ipv4": "ipv4",
            "ipv6": "ipv6",
            "status": "status",
            "connection_type": "connection",
            "direct_connection": "direct_connection",
            "switch_port": "switch_port",
            "switch_name": "switch_name",
            "wifi_speed_mbps": "wifi_speed",
            "wifi_channel": "channel",
            "wifi_signal_strength": "signal",
            "wifi_2_4_speed_mbps": "wifi24_speed",
            "wifi_2_4_channel": "wifi24_channel",
            "wifi_2_4_signal_rx_dbm": "wifi24_signal_rx",
            "wifi_2_4_signal_tx_dbm": "wifi24_signal_tx",
            "wifi_2_4_channel_width": "wifi24_width",
            "wifi_2_4_guest": "wifi24_guest",
            "wifi_5_speed_mbps": "wifi5_speed",
            "wifi_5_channel": "wifi5_channel",
            "wifi_5_signal_rx_dbm": "wifi5_signal_rx",
            "wifi_5_signal_tx_dbm": "wifi5_signal_tx",
            "wifi_5_channel_width": "wifi5_width",
            "wifi_5_guest": "wifi5_guest",
            "device_role": "role",
            "mac_address": "mac",
            "vendor": "vendor",
            "mac_prefix": "prefix",
            "vendor_registry": "registry",
            "vendor_lookup_status": "vendor_status",
            "device_type_detection": "type_detection",
        }
        unique_field = unique_fields.get(field, field)
        self._attr_unique_id = f"{entry.entry_id}_{unique_mac}_{unique_field}"

    def _get_device(self) -> dict | None:
        for device in (self.coordinator.data or []):
            if str(device.get("mac", "")).strip().upper() == self._mac:
                return device
        return None

    @property
    def device_info(self):
        device = self._get_device() or {}
        name = device.get("friendly_name") or device.get("name") or self._mac
        return {
            "identifiers": {(DOMAIN, self._mac)},
            "name": name,
            "manufacturer": "AVM",
            "model": device.get("model"),
        }

    @property
    def extra_state_attributes(self):
        device = self._get_device() or {}
        if self._field in ("switch_port", "switch_name"):
            return {
                "mac_adresse": self._mac,
                "switch_beobachtungen": device.get("switch_connections", []),
                "hinweis": "SNMP-MAC-Tabelle zeigt, auf welchem Port der Switch diese MAC gelernt hat; bei mehreren Switches kann eine MAC auf mehreren Geräten auftauchen.",
            }
        if self._field != "direct_connection":
            return None
        connections = device.get("mesh_direct_connections") or []
        switch_connections = device.get("switch_connections") or []
        lldp_by_host = getattr(self.coordinator, "last_lldp_neighbors", {}) or {}
        lldp_records = [
            record
            for records in lldp_by_host.values()
            for record in records
            if isinstance(record, dict)
        ]
        if lldp_records:
            return {
                "mac_adresse": self._mac,
                "datenquelle": "LLDP-MIB / SNMPv3",
                "lldp_nachbarn": lldp_records,
                "mesh_verbindungen": connections,
                "switch_beobachtungen": switch_connections,
                "hinweis": "LLDP beschreibt direkte Nachbarn eines verwalteten Switches inklusive lokalem und entferntem Port.",
            }
        if switch_connections:
            return {
                "mac_adresse": self._mac,
                "datenquelle": "SNMPv3 BRIDGE-MIB (MAC-Adresstabelle des verwalteten Switches)",
                "verbindungen": switch_connections,
                "mesh_verbindungen": connections,
                "hinweis": "Der Switch hat diese MAC-Adresse auf dem angegebenen Port gelernt. Das belegt den beobachteten Switch-Port, aber bei einem Uplink-Port nicht zwingend eine direkte physische Verbindung des Endgeräts.",
            }
        return {
            "mac_adresse": self._mac,
            "datenquelle": device.get("mesh_direct_connection_source") or "Keine explizite Mesh-Verbindung gefunden",
            "verbindungen": connections,
            "hinweis": "Nur explizite, als CONNECTED gemeldete FRITZ!Box-Mesh-Links; kein Schluss aus Namen oder IP-Adressen.",
        }

    @property
    def native_value(self):
        device = self._get_device()
        if not device:
            return None

        if self._field == "status":
            active = device.get("active")
            if active is None:
                active = device.get("is_online")
            if active is None:
                active = device.get("online")
            return "Online" if active is True else "Offline" if active is False else None

        if self._field == "connection_type":
            return device.get("interface_type") or device.get("connection_type")

        if self._field in ("switch_port", "switch_name"):
            connections = device.get("switch_connections") or []
            if self._field == "switch_port" and len(connections) > 1:
                return "Mehrere Switches"
            if self._field == "switch_name" and len(connections) > 1:
                return "Mehrere Switches"
        if self._field == "switch_port":
            return device.get("switch_port")

        if self._field == "switch_name":
            return device.get("switch_name")

        if self._field == "direct_connection":
            return _direct_connection_info(
                device, self.coordinator.data or [], self.coordinator.switches or [],
                getattr(self.coordinator, "last_lldp_neighbors", {}) or {},
            ).get("label")

        if self._field == "speed_mbps":
            # The generic rate is intended for wired/LAN devices. For WLAN
            # clients, use the band-specific mesh rate sensors instead so the
            # generic value cannot disagree with the active Wi-Fi link rate.
            connection = str(
                device.get("interface_type") or device.get("connection_type") or ""
            ).strip().lower()
            if any(token in connection for token in ("wlan", "wi-fi", "wifi", "802.11", "wireless")):
                return None

        if self._field == "mac_address":
            return self._mac

        if self._field == "model":
            # Prefer the model reported by the FRITZ!Box. If it is missing,
            # fall back to the model manually entered for this MAC/hostname.
            model = device.get("model")
            if model:
                return model
            database = getattr(self.coordinator.client, "device_overrides", None)
            entries = getattr(database, "entries", []) if database else []
            names = {
                str(device.get(key) or "").strip().casefold()
                for key in ("friendly_name", "name")
                if str(device.get(key) or "").strip()
            }
            for entry in entries:
                entry_mac = str(entry.get("mac") or "").strip().replace("-", ":").upper()
                entry_hostname = str(entry.get("hostname") or "").strip().casefold()
                if (entry_mac and entry_mac == self._mac) or (entry_hostname and entry_hostname in names):
                    return entry.get("model") or None
            return None

        if self._field in ("ipv4", "ipv6"):
            wanted = "ipv4" if self._field == "ipv4" else "ipv6"
            for address in device.get("ip_addresses", []) or []:
                if not isinstance(address, dict):
                    continue
                value = address.get("address")
                addrtype = str(address.get("type", "")).lower()
                if value and (
                    (wanted == "ipv4" and (addrtype in ("ipv4", "4") or "." in str(value)))
                    or (wanted == "ipv6" and (addrtype in ("ipv6", "6") or ":" in str(value)))
                ):
                    return value
            return None

        return device.get(self._field)


class MacDatabaseDiagnosticSensor(CoordinatorEntity, SensorEntity):
    """Integration-level diagnostics for the local MAC vendor database."""

    def __init__(self, coordinator, entry: ConfigEntry, field: str) -> None:
        super().__init__(coordinator)
        self._field = field
        self._attr_has_entity_name = True
        self._attr_name = "Herstellerdatenbank-Status" if field == "status" else "Herstellerdatenbank-Einträge"
        self._attr_icon = "mdi:database-check" if field == "status" else "mdi:database"
        self._attr_unique_id = f"{entry.entry_id}_mac_vendor_db_{field}"
        if field == "entries":
            self._attr_native_unit_of_measurement = "Einträge"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "mac_vendor_database")},
            "name": "FRITZ!Box Network Map – Herstellerdatenbank",
            "manufacturer": "IEEE Registry / lokal",
            "model": "MAC-Präfix-Datenbank",
        }

    @property
    def native_value(self):
        database = getattr(self.coordinator.client, "vendor_db", None)
        if database is None:
            return "Nicht verfügbar" if self._field == "status" else 0
        return database.status if self._field == "status" else database.count


class OverrideDatabaseDiagnosticSensor(CoordinatorEntity, SensorEntity):
    """Diagnostics for the user-editable device override database."""

    def __init__(self, coordinator, entry: ConfigEntry, field: str) -> None:
        super().__init__(coordinator)
        self._field = field
        self._attr_has_entity_name = True
        self._attr_name = "Gerätezuordnungen-Status" if field == "status" else "Gerätezuordnungen-Einträge"
        self._attr_icon = "mdi:database-check" if field == "status" else "mdi:format-list-numbered"
        self._attr_unique_id = f"{entry.entry_id}_device_overrides_{field}"
        if field == "entries":
            self._attr_native_unit_of_measurement = "Einträge"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "device_overrides_database")},
            "name": "FRITZ!Box Network Map – Gerätezuordnungen",
            "manufacturer": "Lokal",
            "model": "Manuelle Gerätetyp-Datenbank",
        }

    @property
    def native_value(self):
        database = getattr(self.coordinator.client, "device_overrides", None)
        if database is None:
            return "Nicht verfügbar" if self._field == "status" else 0
        return database.status if self._field == "status" else database.count


class SwitchSNMPDiagnosticSensor(CoordinatorEntity, SensorEntity):
    """Expose the complete latest SNMP MAC-table observations for troubleshooting."""

    NAS_MAC = "90:09:D0:79:05:43"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_name = "SNMP-Switch-Diagnose"
        self._attr_icon = "mdi:database-search"
        self._attr_unique_id = f"{entry.entry_id}_snmp_switch_diagnostics"
        self._attr_native_unit_of_measurement = "MAC-Adressen"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "snmp_switch_diagnostics")},
            "name": "FRITZ!Box Network Map – SNMP-Switch-Diagnose",
            "manufacturer": "FRITZ!Box Network Map",
            "model": "SNMPv3 MAC-Port-Tabelle",
        }

    @property
    def native_value(self):
        records = getattr(self.coordinator, "last_switch_records", {}) or {}
        return len(records)

    @property
    def extra_state_attributes(self):
        records = getattr(self.coordinator, "last_switch_records", {}) or {}
        errors = getattr(self.coordinator, "last_switch_errors", {}) or {}
        switches = getattr(self.coordinator, "switches", []) or []
        nas_records = records.get(self.NAS_MAC, [])
        return {
            "switches": [
                {"name": item.get("name") or item.get("host"), "host": item.get("host"), "port": item.get("port", 161)}
                for item in switches
            ],
            "nas_mac": self.NAS_MAC,
            "nas_mac_found": bool(nas_records),
            "nas_observations": nas_records,
            "snmp_errors": errors,
            "mac_table": records,
            "hinweis": "MAC-Adressen sind vom Switch gelernte Einträge. Ein Eintrag auf einem Uplink-Port beweist keine direkte physische Verbindung des Endgeräts.",
        }


def _direct_connection_info(
    device: dict,
    all_devices: list[dict] | None = None,
    configured_switches: list[dict] | None = None,
    lldp_neighbors: dict[str, list[dict]] | None = None,
) -> dict:
    """Resolve LLDP, then Mesh, then cautious SNMP observations."""
    all_devices = all_devices or []
    configured_switches = configured_switches or []
    lldp_neighbors = lldp_neighbors or {}

    def addresses(item: dict) -> set[str]:
        values = set()
        for address in item.get("ip_addresses") or []:
            if isinstance(address, dict) and address.get("address"):
                values.add(str(address["address"]).strip())
        for key in ("ipv4", "ip", "host"):
            if item.get(key):
                values.add(str(item[key]).strip())
        return values

    # LLDP is the strongest direct-wired-neighbour evidence. Use it only for
    # the configured managed switch whose management address matches this
    # device. Never invent a parent when LLDP has no unique neighbour.
    device_ips = addresses(device)
    device_mac = re.sub(r"[^0-9A-F]", "", str(device.get("mac") or "").upper())
    matching_switches = [
        config for config in configured_switches
        if (
            device_mac
            and re.sub(r"[^0-9A-F]", "", str(config.get("device_mac") or config.get("mac") or "").upper()) == device_mac
        ) or str(config.get("host") or "").strip() in device_ips
    ]
    if len(matching_switches) == 1:
        host = str(matching_switches[0].get("host") or "").strip()
        neighbours = lldp_neighbors.get(host, [])
        if neighbours:
            # Resolve LLDP chassis IDs against the already known FRITZ!Box
            # device inventory. System names such as "fritz.box" are not unique.
            known_by_mac = {
                re.sub(r"[^0-9A-F]", "", str(item.get("mac") or "").upper()): item
                for item in all_devices if item.get("mac")
            }
            resolved = []
            for neighbour in neighbours:
                remote_mac = re.sub(
                    r"[^0-9A-F]", "",
                    str(neighbour.get("remote_chassis_id") or "").upper(),
                )
                target = known_by_mac.get(remote_mac)
                target_name = (
                    target.get("friendly_name") or target.get("name")
                    or target.get("hostname") if target else None
                ) or neighbour.get("remote_system_name") or neighbour.get("remote_chassis_id")
                resolved.append({
                    **neighbour,
                    "target_name": target_name,
                    "target_mac": neighbour.get("remote_chassis_id"),
                    "target_device_mac": target.get("mac") if target else None,
                })
            if len(resolved) == 1:
                item = resolved[0]
                remote_port = item.get("remote_port_id") or item.get("remote_port_description")
                label = item["target_name"]
                if remote_port:
                    label = f"{label} / {remote_port}"
                return {
                    "kind": "ethernet",
                    "target_name": item["target_name"],
                    "target_mac": item.get("target_device_mac") or item.get("target_mac"),
                    "target_host": None,
                    "port": item.get("local_port"),
                    "remote_port": remote_port,
                    "label": label,
                    "source": "lldp",
                    "neighbours": resolved,
                }
            names = [item["target_name"] for item in resolved]
            return {
                "kind": "ethernet_multi",
                "label": f"{len(resolved)} LLDP-Kabelnachbarn: " + ", ".join(names),
                "source": "lldp",
                "neighbours": resolved,
            }

    switch_connections = device.get("switch_connections") or []
    if len(switch_connections) == 1:
        item = switch_connections[0]
        switch_name = item.get("switch_name") or item.get("switch_host") or "Switch"
        port = item.get("switch_port")
        return {
            "kind": "ethernet", "target_name": switch_name,
            "target_host": item.get("switch_host"), "port": port,
            "label": f"{switch_name} / {port}" if port else str(switch_name),
            "source": "switch_connections",
        }
    if len(switch_connections) > 1:
        return {"kind": "ambiguous", "label": "Mehrere Switch-Port-Beobachtungen", "source": "switch_connections"}
    mesh_connections = device.get("mesh_direct_connections") or []
    if mesh_connections:
        # Interpret each node_links record independently. A repeater can have
        # one wired uplink and many WLAN client links; counting records alone
        # incorrectly turns that into "Mehrere Mesh-Verbindungen".
        is_switch = (
            "switch" in str(device.get("device_type") or "").lower()
            or "switch" in str(device.get("device_role") or "").lower()
            or bool(matching_switches)
        )
        wired_neighbours = []
        mesh_neighbours = []
        for connection in mesh_connections:
            links = connection.get("links") or []
            connected_lan = [
                link for link in links
                if str(link.get("link_type") or "").upper() == "LAN"
                and str(link.get("state") or "").upper() == "CONNECTED"
            ]
            connected_wlan = [
                link for link in links
                if str(link.get("link_type") or "").upper() == "WLAN"
                and str(link.get("state") or "").upper() == "CONNECTED"
            ]
            if connected_lan:
                for link in connected_lan:
                    wired_neighbours.append({
                        "target_name": connection.get("neighbour_name") or connection.get("neighbour_mac"),
                        "target_mac": connection.get("neighbour_mac"),
                        "port": link.get("local_interface") or next(iter(connection.get("local_interfaces") or []), None),
                        "remote_port": link.get("neighbour_interface") or next(iter(connection.get("neighbour_interfaces") or []), None),
                        "link_type": "LAN",
                        "state": "CONNECTED",
                        "learned_via_lldp": bool(link.get("learned_via_lldp")),
                        "link_uid": link.get("link_uid"),
                    })
            elif connected_wlan:
                mesh_neighbours.append(connection)
        if wired_neighbours and (is_switch or len(wired_neighbours) == 1):
            if len(wired_neighbours) == 1:
                item = wired_neighbours[0]
                name = item["target_name"]
                port = item.get("port")
                return {
                    "kind": "ethernet",
                    "target_name": name,
                    "target_mac": item.get("target_mac"),
                    "port": port,
                    "remote_port": item.get("remote_port"),
                    "label": f"{name} / {port}" if port else str(name),
                    "source": "fritzbox_node_links",
                    "neighbours": wired_neighbours,
                }
            names = [item["target_name"] for item in wired_neighbours]
            return {
                "kind": "ethernet_multi",
                "label": f"{len(wired_neighbours)} direkte Ethernet-Verbindungen: " + ", ".join(names),
                "source": "fritzbox_node_links",
                "neighbours": wired_neighbours,
            }
        if len(wired_neighbours) > 1:
            return {"kind": "ambiguous", "label": "Mehrere kabelgebundene Nachbarn", "source": "fritzbox_node_links"}
        if len(mesh_neighbours) == 1 and len(mesh_connections) == 1:
            item = mesh_neighbours[0]
            return {
                "kind": "mesh", "target_name": item.get("neighbour_name"),
                "target_mac": item.get("neighbour_mac"),
                "label": str(item.get("neighbour_name") or item.get("neighbour_mac") or ""),
                "source": "mesh_direct_connections",
            }
        if len(mesh_neighbours) == 1 and not wired_neighbours:
            item = mesh_neighbours[0]
            return {
                "kind": "mesh", "target_name": item.get("neighbour_name"),
                "target_mac": item.get("neighbour_mac"),
                "label": str(item.get("neighbour_name") or item.get("neighbour_mac") or ""),
                "source": "mesh_direct_connections",
            }
        if mesh_neighbours or len(mesh_connections) > 1:
            return {"kind": "ambiguous", "label": "Mehrere Mesh-Verbindungen ohne eindeutigen LAN-Uplink", "source": "mesh_direct_connections"}
    if device.get("mesh_node_uids"):
        return {"kind": "none", "label": "Keine direkte Verbindung gemeldet", "source": "mesh"}
    return {"kind": "unknown", "label": "Nicht in Mesh-Daten enthalten", "source": "none"}


class NetworkTopologySensor(CoordinatorEntity, SensorEntity):
    """Single, loss-aware data source for the bundled Lovelace topology card."""

    _attr_has_entity_name = True
    _attr_name = "Netzwerk-Topologie"
    _attr_icon = "mdi:lan"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_network_topology"

    @property
    def native_value(self):
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self):
        client = self.coordinator.client
        model = getattr(client, "network_model", {}) or {}
        devices = []
        for item in (self.coordinator.data or []):
            if not isinstance(item, dict):
                continue
            ip_records = item.get("ip_addresses") or []
            ipv4 = next(
                (entry.get("address") for entry in ip_records
                 if isinstance(entry, dict)
                 and entry.get("type", "").lower() in ("ipv4", "4")
                 and entry.get("address")),
                None,
            )
            if not ipv4:
                ipv4 = next(
                    (entry.get("address") for entry in ip_records
                     if isinstance(entry, dict) and entry.get("address")),
                    None,
                )
            mesh_connections = item.get("mesh_direct_connections") or []
            switch_connections = item.get("switch_connections") or []
            devices.append({
                "mac": item.get("mac"),
                "name": item.get("friendly_name") or item.get("name") or item.get("hostname") or item.get("mac"),
                "model": item.get("model"),
                "manufacturer": item.get("manufacturer") or item.get("vendor"),
                "device_type": item.get("device_type"),
                "device_role": item.get("device_role"),
                "mesh_role": item.get("mesh_role"),
                "status": item.get("status"),
                "active": item.get("active"),
                "ipv4": ipv4,
                "ip_addresses": ip_records,
                "connection_type": item.get("interface_type") or item.get("connection_type"),
                "direct_connection": _direct_connection_info(
                    item, self.coordinator.data or [], self.coordinator.switches or [],
                    getattr(self.coordinator, "last_lldp_neighbors", {}) or {},
                ).get("label"),
                "direct_connection_info": _direct_connection_info(
                    item, self.coordinator.data or [], self.coordinator.switches or [],
                    getattr(self.coordinator, "last_lldp_neighbors", {}) or {},
                ),
                "mesh_direct_connections": mesh_connections,
                "mesh_node_uids": item.get("mesh_node_uids") or [],
                "mesh_wifi_access_node_uid": item.get("mesh_wifi_access_node_uid"),
                "mesh_wifi_interface_uid": item.get("mesh_wifi_interface_uid"),
                "mesh_wifi_link_uid": item.get("mesh_wifi_link_uid"),
                "mesh_wifi_link_state": item.get("mesh_wifi_link_state"),
                "mesh_wifi_band": item.get("mesh_wifi_band"),
                "switch_name": item.get("switch_name"),
                "switch_port": item.get("switch_port"),
                "switch_connections": item.get("switch_connections") or [],
                "switch_connection_excluded_reason": item.get("switch_connection_excluded_reason"),
                "speed_mbps": item.get("speed_mbps"),
                "wifi_speed_mbps": item.get("wifi_speed_mbps"),
                "wifi_2_4_speed_mbps": item.get("wifi_2_4_speed_mbps"),
                "wifi_5_speed_mbps": item.get("wifi_5_speed_mbps"),
                "wifi_channel": item.get("wifi_channel"),
                "wifi_2_4_channel": item.get("wifi_2_4_channel"),
                "wifi_5_channel": item.get("wifi_5_channel"),
            })

        # Mesh links are authoritative node_links. Switch FDB observations are
        # preserved separately and are never silently promoted to proven links.
        mesh_links = []
        for link in model.get("links", []) if isinstance(model, dict) else []:
            if isinstance(link, dict):
                mesh_links.append({
                    "source": link.get("source"),
                    "target": link.get("target"),
                    "type": link.get("type"),
                    "state": link.get("state"),
                    "evidence": link.get("evidence") or "FRITZ!Box node_links",
                })

        mesh_nodes = []
        for uid, node in (model.get("nodes", {}) or {}).items() if isinstance(model, dict) else []:
            if isinstance(node, dict):
                mesh_nodes.append({
                    "uid": uid,
                    "mac": node.get("device_mac_address"),
                    "name": node.get("name"),
                    "mesh_role": node.get("mesh_role"),
                    "interfaces": node.get("interfaces", []),
                })

        mesh_interfaces = []
        for uid, interface in (model.get("interfaces", {}) or {}).items() if isinstance(model, dict) else []:
            if isinstance(interface, dict):
                mesh_interfaces.append({
                    "uid": uid,
                    "node_uid": interface.get("node_uid"),
                    "name": interface.get("name"),
                    "type": interface.get("type"),
                    "mac": interface.get("mac_address"),
                })

        switch_inventory = []
        for host, switch in (model.get("switches", {}) or {}).items() if isinstance(model, dict) else []:
            if isinstance(switch, dict):
                switch_inventory.append({
                    "host": switch.get("host") or host,
                    "name": switch.get("name") or host,
                    "lldp_neighbors": (getattr(self.coordinator, "last_lldp_neighbors", {}) or {}).get(host, []),
                })

        # Canonical topology is a projection of the exact per-device
        # "Direkt verbunden mit" sensor result. Preserve every neighbour of
        # ethernet_multi as well as single Ethernet/Mesh connections.
        topology_edges = []
        source_items = [d for d in (self.coordinator.data or []) if isinstance(d, dict)]
        for item, projected in zip(source_items, devices):
            info = projected.get("direct_connection_info") or {}
            kind = info.get("kind")
            common = {
                "target_mac": projected.get("mac"),
                "label": info.get("label"),
                "evidence": "Sensorwert: Direkt verbunden mit",
            }
            if kind == "ethernet_multi":
                for neighbour in info.get("neighbours") or []:
                    topology_edges.append({
                        **common,
                        "kind": "ethernet",
                        "source_name": neighbour.get("target_name") or neighbour.get("neighbour_name"),
                        "source_mac": neighbour.get("target_mac") or neighbour.get("neighbour_mac"),
                        "switch_host": neighbour.get("target_host"),
                        "port": neighbour.get("port") or neighbour.get("local_interface"),
                        "remote_port": neighbour.get("remote_port"),
                    })
            elif kind == "ethernet":
                topology_edges.append({
                    **common,
                    "kind": "ethernet",
                    "source_name": info.get("target_name"),
                    "source_mac": info.get("target_mac"),
                    "switch_host": info.get("target_host"),
                    "port": info.get("port"),
                    "remote_port": info.get("remote_port"),
                })
            elif kind == "mesh":
                topology_edges.append({
                    **common,
                    "kind": "mesh",
                    "source_name": info.get("target_name"),
                    "source_mac": info.get("target_mac"),
                })

        # Pre-compute display coordinates here, alongside the authoritative sensor
        # edges. The Lovelace card receives ready-to-render nodes and edges only.
        topology_nodes = []
        node_by_id = {}
        def _topology_id(mac_value=None, host_value=None):
            normalized = re.sub(r"[^0-9A-F]", "", str(mac_value or "").upper())
            if normalized:
                return normalized
            host = str(host_value or "").strip().lower()
            return f"HOST:{host}" if host else None

        for device in devices:
            device_mac = device.get("mac")
            node_id = _topology_id(mac_value=device_mac)
            if not node_id:
                continue
            role = str(device.get("device_role") or "").casefold()
            dtype = str(device.get("device_type") or "").casefold()
            mesh_role = str(device.get("mesh_role") or "").casefold()
            if "switch" in role or "switch" in dtype:
                node_kind = "switch"
            elif role in {"mesh-master", "router", "gateway"} or mesh_role == "master":
                node_kind = "router"
            elif role == "repeater" or mesh_role in {"slave", "repeater"}:
                node_kind = "repeater"
            else:
                node_kind = "device"
            node = {
                "id": node_id, "mac": device_mac,
                "name": device.get("friendly_name") or device.get("name") or device.get("hostname") or device_mac,
                "kind": node_kind, "ipv4": device.get("ipv4"),
                "status": device.get("status"), "active": device.get("active"),
                "switch_name": device.get("switch_name"), "switch_port": device.get("switch_port"),
            }
            topology_nodes.append(node)
            node_by_id[node_id] = node

        # Include configured switch endpoints only when they are not already a
        # device in the FRITZ!Box inventory. Their identity comes from config.
        for sw in switch_inventory:
            host = str(sw.get("host") or "").strip()
            if not host:
                continue
            already_present = any(str(n.get("ipv4") or "") == host for n in topology_nodes)
            if already_present:
                continue
            node_id = _topology_id(host_value=host)
            if node_id not in node_by_id:
                node = {"id": node_id, "mac": None, "name": sw.get("name") or host,
                        "kind": "switch", "ipv4": host, "synthetic": True}
                topology_nodes.append(node)
                node_by_id[node_id] = node

        # Resolve endpoints of an already-declared sensor edge. Prefer MAC
        # identity; FRITZ!Box node_links can expose an interface MAC instead
        # of the LAN-device MAC, so use the exact neighbour name as a fallback
        # to an existing inventory node. This does not create or infer edges.
        node_ids_by_name = {
            str(node.get("name") or "").strip().casefold(): node["id"]
            for node in topology_nodes
            if node.get("name") and node.get("id")
        }
        node_ids_by_ip = {
            str(node.get("ipv4") or "").strip(): node["id"]
            for node in topology_nodes
            if node.get("ipv4") and node.get("id")
        }

        def _resolve_existing_node_id(mac_value=None, name_value=None, host_value=None):
            # Resolve only an endpoint already represented by a topology node.
            # A configured switch is usually referenced by management IP in
            # switch observations, while its inventory node is keyed by MAC.
            # Match that IP to the existing node instead of creating a second
            # synthetic HOST:<ip> identity or leaving the edge dangling.
            # For configured switch observations, switch_host is the
            # management IP of the switch whose FDB supplied the port.
            # Resolve that exact inventory device first. source_mac may be
            # an interface/chassis MAC and must not override the configured
            # switch identity when both are present.
            host_key = str(host_value or "").strip()
            if host_key and host_key in node_ids_by_ip:
                return node_ids_by_ip[host_key]
            host_id = _topology_id(host_value=host_value)
            if host_id in node_by_id:
                return host_id
            mac_id = _topology_id(mac_value=mac_value)
            if mac_id in node_by_id:
                return mac_id
            name_key = str(name_value or "").strip().casefold()
            return node_ids_by_name.get(name_key)

        for edge in topology_edges:
            edge["source_id"] = _resolve_existing_node_id(
                mac_value=edge.get("source_mac"),
                name_value=edge.get("source_name"),
                host_value=edge.get("switch_host"),
            )
            edge["target_id"] = _resolve_existing_node_id(
                mac_value=edge.get("target_mac"),
                name_value=edge.get("target_name"),
            )

        # Layout only: retain exactly the sensor-provided directed edges.
        # A depth-first subtree layout keeps each parent's children together,
        # unlike the former breadth-first rows which scattered siblings and
        # produced many crossing lines. No edge is added, removed or inferred.
        incoming = {
            edge.get("target_id")
            for edge in topology_edges
            if edge.get("source_id") in node_by_id and edge.get("target_id") in node_by_id
        }
        children = {node["id"]: [] for node in topology_nodes}
        for edge in topology_edges:
            source_id, target_id = edge.get("source_id"), edge.get("target_id")
            if source_id in children and target_id in children and target_id not in children[source_id]:
                children[source_id].append(target_id)

        kind_order = {"router": 0, "switch": 1, "repeater": 2, "device": 3}
        def _node_sort_key(node_id):
            node = node_by_id[node_id]
            return (kind_order.get(node.get("kind"), 4), str(node.get("name") or "").casefold())

        for parent_id in children:
            children[parent_id].sort(key=_node_sort_key)

        roots = [node["id"] for node in topology_nodes if node["id"] not in incoming]
        roots.sort(key=_node_sort_key)
        ordered_roots = list(roots)
        visited = set()
        leaf_index = 0
        positions = {}

        def _place_subtree(node_id, depth):
            nonlocal leaf_index
            if node_id in visited:
                return positions.get(node_id, (depth, 54 + leaf_index * 104))[1]
            visited.add(node_id)
            child_ids = [child for child in children.get(node_id, []) if child not in visited]
            if not child_ids:
                y = 54 + leaf_index * 104
                leaf_index += 1
            else:
                child_y = [_place_subtree(child_id, depth + 1) for child_id in child_ids]
                y = sum(child_y) / len(child_y)
            positions[node_id] = (depth, y)
            return y

        for root_id in ordered_roots:
            _place_subtree(root_id, 0)

        # Include isolated nodes and any nodes in a directed cycle as separate
        # layout roots; this changes placement only, never their connections.
        for node in topology_nodes:
            if node["id"] not in visited:
                _place_subtree(node["id"], 0)

        for node in topology_nodes:
            depth, y = positions.get(node["id"], (0, 54))
            node["x"] = 48 + depth * 300
            node["y"] = y

        # Group terminal devices visually under their already-declared direct
        # connection partner. The groups are derived only from topology_edges
        # emitted above; no additional parent/child relationship is inferred.
        topology_groups = []
        grouped_member_ids = set()
        topology_display_edges = []
        for parent_id, child_ids in children.items():
            terminal_ids = [
                child_id for child_id in child_ids
                if not children.get(child_id)
            ]
            if not terminal_ids:
                continue
            parent = node_by_id[parent_id]
            terminal_ids.sort(key=_node_sort_key)
            member_y = min(node_by_id[item]["y"] for item in terminal_ids)
            group_x = parent["x"] + 300
            group_y = member_y - 28
            group_height = max(112, len(terminal_ids) * 104 + 32)
            group = {
                "id": f"group:{parent_id}",
                "parent_id": parent_id,
                "parent_name": parent.get("name"),
                "member_ids": terminal_ids,
                "x": group_x,
                "y": group_y,
                "width": 260,
                "height": group_height,
                "title": f"Direkt verbunden mit {parent.get('name') or 'Gerät'}",
            }
            topology_groups.append(group)
            for index, member_id in enumerate(terminal_ids):
                member = node_by_id[member_id]
                member["group_id"] = group["id"]
                member["x"] = group_x + 20
                member["y"] = group_y + 24 + index * 104
                grouped_member_ids.add(member_id)

        # Keep only links between ungrouped/main devices in the main diagram.
        # Connections to grouped terminal devices are represented by one
        # parent-to-group connector in the renderer.
        for edge in topology_edges:
            if edge.get("target_id") not in grouped_member_ids:
                topology_display_edges.append(edge)

        return {
            "devices": devices,
            "topology_nodes": topology_nodes,
            "topology_edges": topology_edges,
            "topology_display_edges": topology_display_edges,
            "topology_groups": topology_groups,
            "mesh_links": mesh_links,
            "mesh_nodes": mesh_nodes,
            "mesh_interfaces": mesh_interfaces,
            "switches": switch_inventory,
            "switch_observations": model.get("switch_links", []) if isinstance(model, dict) else [],
            "switch_errors": model.get("switch_errors", {}) if isinstance(model, dict) else {},
            "last_updated": getattr(self.coordinator, "last_update_success_time", None).isoformat()
                if getattr(self.coordinator, "last_update_success_time", None) else None,
            "card_resource": "/fritz_network_map/fritz-network-map-card.js",
        }
