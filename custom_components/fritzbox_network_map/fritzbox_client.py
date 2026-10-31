from __future__ import annotations

import hashlib
import logging
from urllib.parse import quote, urljoin
from xml.etree import ElementTree

from aiohttp import ClientError, ClientSession

from .hosts import merge_tr064_data, merge_wlan_data
from .mac_vendor import MacVendorDatabase
from .device_overrides import DeviceOverrideDatabase
from .mesh_topology import apply_mesh_roles, async_get_mesh_topology, summarize_mesh_macs, build_mesh_mac_aliases
from .network_model import build_shared_mesh_model, enrich_device_records, validate_mesh_topology
from .wlan import async_get_wlan_devices
from .tr064 import async_tr064_request, digest_authorization

_LOGGER = logging.getLogger(__name__)


class FritzBoxError(Exception):
    """Base error for FRITZ!Box communication."""


class FritzBoxAuthError(FritzBoxError):
    """Authentication failed."""


class FritzBoxClient:
    """Async FRITZ!Box client using the existing API plus optional TR-064 enrichment."""

    def __init__(self, session: ClientSession, host: str, username: str, password: str):
        self.session = session
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        from pathlib import Path
        self.vendor_db = MacVendorDatabase(Path(__file__).with_name("mac_vendors.csv"))
        self.device_overrides = DeviceOverrideDatabase(Path(__file__).with_name("device_overrides.csv"))
        # Persistent in-memory snapshot of the latest FRITZ!Box mesh response.
        self.mesh_model: dict = build_shared_mesh_model({})
        self.network_model: dict = self.mesh_model
        # Keep the complete source JSON responses, not only normalized fields.
        self.landevice_payload: dict = {}

    async def async_get_devices(self) -> list[dict]:
        sid = await self._async_get_sid()
        devices = await self._async_get_landevice(sid)

        # TR-064 is optional: retain the working API result if this service
        # is disabled, unsupported, or unavailable on this FRITZ!OS version.
        try:
            extra = await self._async_get_tr064_hosts()
            merge_tr064_data(devices, extra)
            _LOGGER.info(
                "TR-064-Hostliste erfolgreich gelesen: %s zusätzliche/abgeglichene Geräte; Gesamtbestand: %s.",
                len(extra), len(devices),
            )
        except Exception as err:
            # Keep the working API result if the optional Hosts service fails.
            _LOGGER.warning(
                "TR-064-Hostliste konnte nicht gelesen werden (%s): %s",
                type(err).__name__, err,
                exc_info=True,
            )

        # Fetch WLAN readings now, but merge them only after the mesh response
        # is available. A repeater can expose several interface MACs; the mesh
        # document is needed to map those aliases to the LAN-list device.
        wlan_devices = []
        try:
            wlan_devices = await async_get_wlan_devices(self, FritzBoxError)
            _LOGGER.warning("FRITZ!Box WLAN-LISTE: %s", wlan_devices)
            _LOGGER.info("TR-064-WLAN-Liste gelesen: %s WLAN-Datensätze.", len(wlan_devices))

        except Exception as err:
            _LOGGER.warning(
                "TR-064-WLAN-Liste konnte nicht gelesen werden (%s): %s",
                type(err).__name__,
                err,
                exc_info=True,
            )
        
        _LOGGER.warning(
            "FRITZ!Box LAN-LISTE: %s",
            [
                {
                    "mac": d.get("mac"),
                    "name": d.get("name"),
                    "friendly_name": d.get("friendly_name"),
                    "speed_mbps": d.get("speed_mbps"),
                    "interface_type": d.get("interface_type"),
                    "sources": d.get("sources"),
                }
                for d in devices
            ],
        )

        # Diagnostic: read the mesh topology to identify the access point
        # associated with each client. This does not alter the device records.
        try:
            mesh = await async_get_mesh_topology(self)
            mesh_records = summarize_mesh_macs(mesh)
            # Build a reusable structured representation from the complete raw
            # payload; keep every node/interface's original fields under ``raw``.
            mesh_mac_aliases = build_mesh_mac_aliases(devices, mesh)
            _LOGGER.warning("FRITZ!Box MESH-MAC-ALIASE: %s", mesh_mac_aliases)
            merge_wlan_data(devices, wlan_devices, mesh_mac_aliases)
            _LOGGER.warning(
                "FRITZ!Box NACH WLAN-/MESH-MAC-ABGLEICH: %s",
                [{"mac": d.get("mac"), "name": d.get("name"),
                  "wifi_2_4_speed_mbps": d.get("wifi_2_4_speed_mbps"),
                  "wifi_2_4_channel": d.get("wifi_2_4_channel"),
                  "wifi_5_speed_mbps": d.get("wifi_5_speed_mbps"),
                  "wifi_5_channel": d.get("wifi_5_channel"),
                  "wlan_mac_aliases": d.get("wlan_mac_aliases")} for d in devices],
            )
            self.mesh_model = build_shared_mesh_model(
                mesh, self.landevice_payload, devices
            )
            self.network_model = self.mesh_model
            enrich_device_records(devices, self.mesh_model)
            apply_mesh_roles(devices, mesh)
            mesh_wlan_sensor_records = [
                {
                    "mac": d.get("mac"),
                    "name": d.get("friendly_name") or d.get("name"),
                    "band": d.get("mesh_wifi_band"),
                    "channel": d.get("wifi_channel"),
                    "width": d.get("wifi_channel_width"),
                    "speed_mbps": d.get("wifi_speed_mbps"),
                    "signal_rx_dbm": d.get("wifi_2_4_signal_rx_dbm", d.get("wifi_5_signal_rx_dbm")),
                    "signal_tx_dbm": d.get("wifi_2_4_signal_tx_dbm", d.get("wifi_5_signal_tx_dbm")),
                    "link_state": d.get("mesh_wifi_link_state"),
                    "access_node_uid": d.get("mesh_wifi_access_node_uid"),
                }
                for d in devices if d.get("mesh_wifi_link_uid")
            ]
            _LOGGER.warning(
                "FRITZ!Box MESH-WLAN-SENSORWERTE: %s",
                mesh_wlan_sensor_records,
            )
            _LOGGER.warning(
                "FRITZ!Box GEMEINSAMES NETZWERKMODELL: nodes=%s interfaces=%s devices=%s LAN-JSON-Datensaetze=%s Links=%s",
                len(self.mesh_model.get("nodes", {})),
                len(self.mesh_model.get("interfaces", {})),
                len(self.mesh_model.get("devices", {})),
                len(self.mesh_model.get("source_payloads", {}).get("landevice", {}).get("landevice", [])),
                len(self.mesh_model.get("links", [])),
            )
            topology_validation = validate_mesh_topology(mesh)
            _LOGGER.warning("FRITZ!Box TOPOLOGIE-VALIDIERUNG: %s", topology_validation)
            _LOGGER.warning(
                "FRITZ!Box MESH-TOPOLOGIE: top_level_keys=%s; MAC-Datensaetze=%s",
                list(mesh.keys()) if isinstance(mesh, dict) else type(mesh).__name__,
                mesh_records,
            )
            # Temporary, bounded schema diagnostic: inspect actual raw fields rather
            # than guessing link semantics from interface names or MAC addresses.
            raw_nodes = mesh.get("nodes", []) if isinstance(mesh, dict) else []
            if not isinstance(raw_nodes, list):
                raw_nodes = []
            node_key_sets = {}
            interface_key_sets = {}
            relationship_fields = {}
            selected_raw_nodes = []
            raw_node_link_records = []
            tokens = ("link", "parent", "uplink", "connect", "peer", "target", "source", "path", "relation", "interface", "rate", "speed", "signal", "channel", "band", "rcpi", "rssi")
            for node_index, raw_node in enumerate(raw_nodes):
                if not isinstance(raw_node, dict):
                    continue
                node_keys = tuple(sorted(raw_node.keys()))
                node_key_sets[str(node_keys)] = node_key_sets.get(str(node_keys), 0) + 1
                for key, value in raw_node.items():
                    if any(token in str(key).lower() for token in tokens):
                        relationship_fields.setdefault("node", []).append({"node": raw_node.get("uid", node_index), "field": key, "value": value})
                interfaces = raw_node.get("node_interfaces", [])
                if not isinstance(interfaces, list):
                    continue
                selected_interfaces = []
                for int_index, raw_int in enumerate(interfaces):
                    if not isinstance(raw_int, dict):
                        continue
                    int_keys = tuple(sorted(raw_int.keys()))
                    interface_key_sets[str(int_keys)] = interface_key_sets.get(str(int_keys), 0) + 1
                    interesting = {k: v for k, v in raw_int.items() if any(token in str(k).lower() for token in tokens)}
                    if interesting:
                        relationship_fields.setdefault("interface", []).append({"node": raw_node.get("uid", node_index), "interface": raw_int.get("uid", int_index), "fields": interesting})
                    # Keep every raw node_link exactly as supplied by AVM. In
                    # particular, do not restrict this diagnostic to interfaces
                    # whose names start with UPLINK: signal fields may be present
                    # on the peer-side interface or on a differently named link.
                    raw_links = raw_int.get("node_links", [])
                    if isinstance(raw_links, list):
                        for link_index, raw_link in enumerate(raw_links):
                            if isinstance(raw_link, dict):
                                raw_node_link_records.append({
                                    "node_uid": raw_node.get("uid"),
                                    "node_name": raw_node.get("name") or raw_node.get("device_friendly_name"),
                                    "node_mesh_role": raw_node.get("mesh_role"),
                                    "interface_uid": raw_int.get("uid"),
                                    "interface_name": raw_int.get("name"),
                                    "interface_type": raw_int.get("type"),
                                    "interface_mac_address": raw_int.get("mac_address"),
                                    "link_index": link_index,
                                    "raw_node_link": raw_link,
                                })
                    if str(raw_int.get("name", "")).upper().startswith("UPLINK"):
                        selected_interfaces.append(raw_int)
                if str(raw_node.get("mesh_role", "")).lower() in {"master", "slave"}:
                    selected_raw_nodes.append({
                        "uid": raw_node.get("uid"),
                        "mesh_role": raw_node.get("mesh_role"),
                        "node_keys": node_keys,
                        "raw_node_fields": {k: v for k, v in raw_node.items() if k != "node_interfaces"},
                        "uplink_interfaces": selected_interfaces,
                    })
            _LOGGER.warning("FRITZ!Box MESH-RAW-SCHEMA: node_key_sets=%s interface_key_sets=%s", node_key_sets, interface_key_sets)
            _LOGGER.warning("FRITZ!Box MESH-RAW-BEZIEHUNGSFELDER: %s", relationship_fields)
            _LOGGER.warning("FRITZ!Box MESH-RAW-MASTER-REPEATER: %s", selected_raw_nodes)
            _LOGGER.warning(
                "FRITZ!Box MESH-RAW-NODE-LINKS: count=%s records=%s",
                len(raw_node_link_records), raw_node_link_records,
            )
            _LOGGER.warning(
                "FRITZ!Box GERÄTEROLLEN: %s",
                [{"mac": d.get("mac"), "name": d.get("friendly_name") or d.get("name"), "device_role": d.get("device_role")} for d in devices],
            )
        except Exception as err:
            # If mesh retrieval fails, still expose only conservative roles from
            # the already known connection type/WLAN fields.
            merge_wlan_data(devices, wlan_devices)
            apply_mesh_roles(devices, {})
            self.mesh_model = build_shared_mesh_model(
                {}, self.landevice_payload, devices
            )
            self.network_model = self.mesh_model
            _LOGGER.warning(
                "FRITZ!Box MESH-TOPOLOGIE konnte nicht gelesen werden (%s): %s",
                type(err).__name__, err, exc_info=True,
            )

        # Apply automatic manufacturer lookup first, then manual overrides.
        # Manual values always win over detected mesh/vendor data.
        for device in devices:
            # First populate automatic values. Overrides are applied field by field:
            # an empty CSV cell must never erase an automatically detected value.
            device.update(self.vendor_db.lookup(device.get("mac")))
            override = self.device_overrides.lookup(device)
            device.update(override)  # metadata only (override_*); source fields stay untouched

            if override.get("override_model"):
                device["model"] = override["override_model"]

            if override.get("override_manufacturer"):
                device["manufacturer"] = override["override_manufacturer"]
                device["vendor"] = override["override_manufacturer"]
                device["vendor_lookup_status"] = "Manuell zugeordnet"

            if override.get("override_device_type"):
                device["device_type"] = override["override_device_type"]
                device["device_type_detection"] = (
                    f"Manuell zugeordnet ({override['override_match']})"
                )
            else:
                # No device_type value in the CSV: preserve any existing value.
                # Only fill the explanatory detection text; do not overwrite type.
                model_name = " ".join(
                    str(device.get(key) or "")
                    for key in ("model", "friendly_name", "name")
                ).lower()
                role = str(device.get("device_role") or "").strip()
                if role in {"Mesh-Master", "Repeater", "WLAN-Client", "LAN-Client"}:
                    detection = f"Aus Verbindung/Mesh: {role}"
                elif any(token in model_name for token in ("switch", "netzwerkswitch", "ethernet switch")):
                    detection = "Switch-Hinweis in Modell/Name (bitte prüfen)"
                elif device.get("vendor_lookup_status") == "Treffer":
                    detection = "Hersteller erkannt; Gerätetyp nicht ableitbar"
                else:
                    detection = "Gerätetyp nicht eindeutig erkannt"
                device["device_type_detection"] = detection

            # An empty role cell means the role from mesh/connection detection remains.
            if override.get("override_device_role"):
                device["device_role"] = override["override_device_role"]

        _LOGGER.warning(
            "MAC-HERSTELLER-STATUS: geladen=%s, Einträge=%s, Status=%s, Datei=%s",
            self.vendor_db.loaded, self.vendor_db.count, self.vendor_db.status, self.vendor_db.csv_path,
        )
        _LOGGER.warning(
            "GERÄTEZUORDNUNGS-STATUS: geladen=%s, Einträge=%s, Status=%s, Datei=%s",
            self.device_overrides.loaded, self.device_overrides.count,
            self.device_overrides.status, self.device_overrides.csv_path,
        )
        _LOGGER.warning(
            "GERÄTEZUORDNUNGS-ERGEBNISSE: %s",
            [{"mac": d.get("mac"), "name": d.get("friendly_name") or d.get("name"),
              "device_type": d.get("device_type"), "device_role": d.get("device_role"),
              "override_match": d.get("override_match")} for d in devices],
        )
        _LOGGER.warning(
            "MAC-HERSTELLER-ERGEBNISSE: %s",
            [{"mac": d.get("mac"), "vendor": d.get("vendor"), "mac_prefix": d.get("mac_prefix"),
              "vendor_registry": d.get("vendor_registry"), "vendor_lookup_status": d.get("vendor_lookup_status"),
              "device_type_detection": d.get("device_type_detection")} for d in devices],
        )
        return devices

    async def _async_get_landevice(self, sid: str) -> list[dict]:
        url = f"{self.host}/api/v0/generic/landevice"
        headers = {"Authorization": f"AVM-SID {sid}"}
        async with self.session.get(url, headers=headers, timeout=20) as response:
            if response.status in (401, 403):
                raise FritzBoxAuthError("FRITZ!Box hat den Zugriff abgelehnt.")
            response.raise_for_status()
            payload = await response.json(content_type=None)

        # Retain the entire second JSON document exactly as returned by the API.
        self.landevice_payload = payload if isinstance(payload, dict) else {}
        raw_devices = payload.get("landevice")
        if not isinstance(raw_devices, list):
            raise FritzBoxError("Antwort enthält kein gültiges 'landevice'-Array.")

        devices = []
        for item in raw_devices:
            if not isinstance(item, dict):
                continue
            mac = item.get("mac")
            if not mac:
                continue
            ips = []
            for container in item.get("iplist", []) or []:
                if not isinstance(container, dict):
                    continue
                entries = container.get("entry", [])
                if isinstance(entries, dict):
                    entries = [entries]
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("ip"):
                        ips.append({
                            "address": str(entry["ip"]),
                            "type": str(entry.get("addrtype", "unknown")),
                        })
            devices.append({
                "mac": str(mac).upper(),
                "name": item.get("name"),
                "friendly_name": item.get("friendlyname"),
                "ip_addresses": ips,
                "source": "fritzbox_landevice",
                "raw_landevice": item,
            })
        return devices

    async def _async_get_tr064_hosts(self) -> list[dict]:
        """Read the official TR-064 host list path and parse its XML response."""
        control_url = f"{self.host}:49000/upnp/control/hosts"
        service = "urn:dslforum-org:service:Hosts:1"
        soap = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            '<s:Body><u:X_AVM-DE_GetHostListPath '
            'xmlns:u="urn:dslforum-org:service:Hosts:1"/></s:Body></s:Envelope>'
        )
        response_xml = await self._async_tr064_request(control_url, service, "X_AVM-DE_GetHostListPath", soap)
        root = ElementTree.fromstring(response_xml)
        path = self._find_text_by_local_name(root, "NewX_AVM-DE_HostListPath")
        if not path:
            raise FritzBoxError("TR-064 lieferte keinen Host-Listen-Pfad.")

        list_url = urljoin(f"{self.host}:49000/", path.lstrip("/"))
        async with self.session.get(list_url, timeout=20) as response:
            response.raise_for_status()
            list_xml = await response.text()

        list_root = ElementTree.fromstring(list_xml)
        hosts: list[dict] = []
        for item in list_root.iter():
            if self._local_name(item.tag) != "Item":
                continue
            fields = {self._local_name(child.tag): (child.text or "").strip() for child in item}
            mac = fields.get("MACAddress", "").upper()
            if not mac:
                continue
            hosts.append({
                "mac": mac,
                "name": fields.get("HostName") or None,
                "friendly_name": fields.get("X_AVM-DE_FriendlyName") or None,
                "interface_type": fields.get("InterfaceType") or None,
                "active": self._parse_bool(fields.get("Active")),
                "port": self._parse_int(fields.get("X_AVM-DE_Port")),
                "speed_mbps": self._parse_int(fields.get("X_AVM-DE_Speed")),
                "model": fields.get("X_AVM-DE_Model") or None,
                "is_meshable": self._parse_bool(fields.get("X_AVM-DE_IsMeshable")),
                "is_guest": self._parse_bool(fields.get("X_AVM-DE_Guest")),
                "device_class": fields.get("X_AVM-DE_DeviceClass") or None,
                "device_class_user": fields.get("X_AVM-DE_DeviceClassUser") or None,
                "source": "tr064_hosts",
            })
        return hosts

    async def _async_tr064_request(self, url: str, service: str, action: str, soap_body: str) -> str:
        """Compatibility wrapper for the dedicated TR-064 transport module."""
        return await async_tr064_request(
            session=self.session,
            username=self.username,
            password=self.password,
            url=url,
            service=service,
            action=action,
            soap_body=soap_body,
            auth_error_cls=FritzBoxAuthError,
        )

    def _digest_authorization(self, challenge: str, method: str, url: str) -> str | None:
        """Compatibility wrapper; Digest header generation lives in tr064.py."""
        return digest_authorization(
            challenge=challenge,
            method=method,
            url=url,
            username=self.username,
            password=self.password,
        )

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    @classmethod
    def _find_text_by_local_name(cls, root: ElementTree.Element, name: str) -> str | None:
        for element in root.iter():
            if cls._local_name(element.tag) == name:
                return (element.text or "").strip()
        return None

    @staticmethod
    def _parse_bool(value: str | None) -> bool | None:
        if value is None or value == "":
            return None
        return value.strip() in ("1", "true", "True")

    @staticmethod
    def _parse_int(value: str | None) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (ValueError, TypeError):
            return None

    async def _async_get_sid(self) -> str:
        login_url = f"{self.host}/login_sid.lua?version=2&username={quote(self.username, safe='')}"
        try:
            async with self.session.get(login_url, timeout=20) as response:
                response.raise_for_status()
                challenge_xml = await response.text()
            root = ElementTree.fromstring(challenge_xml)
            challenge = root.findtext("Challenge", default="").strip()
            if not challenge.startswith("2$"):
                raise FritzBoxAuthError("Nicht unterstütztes FRITZ!Box-Anmeldeverfahren.")
            response_value = self._pbkdf2_response(challenge, self.password)
            response_url = (
                f"{self.host}/login_sid.lua?version=2"
                f"&username={quote(self.username, safe='')}"
                f"&response={quote(response_value, safe='')}"
            )
            async with self.session.get(response_url, timeout=20) as response:
                response.raise_for_status()
                login_xml = await response.text()
            login_root = ElementTree.fromstring(login_xml)
            sid = login_root.findtext("SID", default="").strip()
            if not sid or sid == "0000000000000000":
                raise FritzBoxAuthError("Anmeldung fehlgeschlagen. Benutzername oder Passwort prüfen.")
            return sid
        except FritzBoxAuthError:
            raise
        except (ClientError, ValueError, ElementTree.ParseError) as err:
            raise FritzBoxError(f"Fehler bei der FRITZ!Box-Anmeldung: {err}") from err

    @staticmethod
    def _pbkdf2_response(challenge: str, password: str) -> str:
        parts = challenge.split("$")
        if len(parts) != 5 or parts[0] != "2":
            raise FritzBoxAuthError("Ungültiges PBKDF2-Challenge-Format.")
        try:
            iterations1 = int(parts[1])
            salt1 = bytes.fromhex(parts[2])
            iterations2 = int(parts[3])
            salt2 = bytes.fromhex(parts[4])
        except (ValueError, TypeError) as err:
            raise FritzBoxAuthError("Ungültige FRITZ!Box-Challenge.") from err
        hash1 = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt1, iterations1, dklen=32)
        hash2 = hashlib.pbkdf2_hmac("sha256", hash1, salt2, iterations2, dklen=32)
        return f"{salt2.hex()}${hash2.hex()}"
