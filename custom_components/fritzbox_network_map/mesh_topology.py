"""Mesh topology retrieval and diagnostic parsing for FRITZ!Box Network Map."""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin
from xml.etree import ElementTree


_LOGGER = logging.getLogger(__name__)
_MAC_PATTERN = re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def _norm_mac(value) -> str | None:
    """Normalize a valid MAC address."""
    if not isinstance(value, str):
        return None
    value = value.strip().replace("-", ":").upper()
    return value if _MAC_PATTERN.match(value) else None


async def async_get_mesh_topology(client) -> dict:
    """Read the FRITZ!Box mesh topology JSON via the documented Hosts service."""
    control_url = f"{client.host}:49000/upnp/control/hosts"
    service = "urn:dslforum-org:service:Hosts:1"
    soap = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body><u:X_AVM-DE_GetMeshListPath '
        'xmlns:u="urn:dslforum-org:service:Hosts:1"/></s:Body></s:Envelope>'
    )
    response_xml = await client._async_tr064_request(
        control_url, service, "X_AVM-DE_GetMeshListPath", soap
    )
    root = ElementTree.fromstring(response_xml)
    path = client._find_text_by_local_name(root, "NewX_AVM-DE_MeshListPath")
    if not path:
        raise ValueError("TR-064 lieferte keinen Mesh-Listen-Pfad.")

    list_url = urljoin(f"{client.host}:49000/", path.lstrip("/"))
    async with client.session.get(list_url, timeout=20) as response:
        response.raise_for_status()
        payload = await response.text()

    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Die Mesh-Topologie ist kein JSON-Objekt.")
    return data


def summarize_mesh_macs(data) -> list[dict]:
    """Extract small diagnostic records around MAC-address values from mesh JSON."""
    wanted = {
        "name", "friendly_name", "hostname", "model", "role", "mesh_role",
        "type", "state", "connection", "connection_type", "interface_type",
        "band", "channel", "speed", "rate", "uid", "mac", "mac_address",
        "connected_via", "parent", "target", "link",
    }
    records = []
    seen = set()

    def walk(value, path="$"):
        if isinstance(value, dict):
            mac_values = {
                str(k): str(v).upper()
                for k, v in value.items()
                if isinstance(v, str) and _MAC_PATTERN.match(v.strip())
            }
            if mac_values:
                record = {"path": path}
                for key, item in value.items():
                    if key.lower() in wanted and isinstance(item, (str, int, float, bool)):
                        record[key] = item
                    if key in mac_values:
                        record[key] = mac_values[key]
                marker = json.dumps(record, sort_keys=True, default=str)
                if marker not in seen:
                    seen.add(marker)
                    records.append(record)
            for key, item in value.items():
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(data)
    return records


def build_mesh_mac_aliases(devices: list[dict], data: dict) -> dict[str, str]:
    """Map mesh-interface MACs to an existing LAN-list device MAC.

    Only MACs listed on the same mesh node are grouped. The existing device
    record is preferred by matching a LANBridge interface, then a LAN
    interface, then the node's device MAC, then any existing MAC on the node.
    """
    by_mac = {
        str(device.get("mac", "")).strip().upper(): device
        for device in devices
        if isinstance(device, dict) and _norm_mac(device.get("mac"))
    }
    aliases: dict[str, str] = {}
    nodes = data.get("nodes", []) if isinstance(data, dict) else []
    if not isinstance(nodes, list):
        return aliases

    for node in nodes:
        if not isinstance(node, dict):
            continue

        node_macs: list[str] = []
        interface_records = []
        node_mac = _norm_mac(node.get("device_mac_address"))
        if node_mac:
            node_macs.append(node_mac)

        interfaces = node.get("node_interfaces", [])
        if isinstance(interfaces, list):
            for interface in interfaces:
                if not isinstance(interface, dict):
                    continue
                mac = _norm_mac(interface.get("mac_address"))
                if mac and mac not in node_macs:
                    node_macs.append(mac)
                if mac:
                    interface_records.append((str(interface.get("type", "")).upper(), mac))

        existing = [mac for mac in node_macs if mac in by_mac]
        if not existing:
            continue

        preferred = None
        for wanted_type in ("LANBRIDGE", "LAN", "ETHERNET"):
            preferred = next(
                (mac for kind, mac in interface_records if kind == wanted_type and mac in by_mac),
                None,
            )
            if preferred:
                break
        if preferred is None and node_mac in by_mac:
            preferred = node_mac
        if preferred is None:
            preferred = existing[0]

        for mac in node_macs:
            if mac != preferred:
                aliases[mac] = preferred

        _LOGGER.debug(
            "Mesh-MAC-Aliase: Knoten=%s, Haupt-MAC=%s, Aliase=%s",
            node.get("name") or node.get("uid") or node_mac,
            preferred,
            [mac for mac in node_macs if mac != preferred],
        )

    return aliases


def apply_mesh_roles(devices: list[dict], data: dict) -> None:
    """Add a conservative, human-readable role to devices using mesh data."""
    mac_roles: dict[str, str] = {}

    nodes = data.get("nodes", []) if isinstance(data, dict) else []
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            mesh_role = str(node.get("mesh_role", "")).strip().lower()
            if mesh_role == "master":
                role = "Mesh-Master"
            elif mesh_role == "slave":
                role = "Repeater"
            else:
                role = None

            macs = set()
            node_mac = _norm_mac(node.get("device_mac_address"))
            if node_mac:
                macs.add(node_mac)

            interface_types = set()
            interfaces = node.get("node_interfaces", [])
            if isinstance(interfaces, list):
                for interface in interfaces:
                    if not isinstance(interface, dict):
                        continue
                    interface_mac = _norm_mac(interface.get("mac_address"))
                    if interface_mac:
                        macs.add(interface_mac)
                    interface_type = str(interface.get("type", "")).strip().upper()
                    if interface_type:
                        interface_types.add(interface_type)

            if role is None:
                if "WLAN" in interface_types or "WIFI" in interface_types:
                    role = "WLAN-Client"
                elif "LAN" in interface_types or "ETHERNET" in interface_types:
                    role = "LAN-Client"

            if role:
                for mac in macs:
                    mac_roles[mac] = role

    for device in devices:
        if not isinstance(device, dict):
            continue
        mac = _norm_mac(device.get("mac"))
        role = mac_roles.get(mac) if mac else None
        if not role:
            interface = str(device.get("interface_type") or device.get("connection_type") or "").strip().lower()
            if interface in {"802.11", "wlan", "wifi", "wireless"} or device.get("wifi_channel") is not None or device.get("wifi_speed_mbps") is not None:
                role = "WLAN-Client"
            elif interface in {"ethernet", "lan", "802.3", "wired"}:
                role = "LAN-Client"
            else:
                role = "Unbekannt"
        device["device_role"] = role
