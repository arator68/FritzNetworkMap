"""Lossless shared data model for FRITZ!Box Mesh and LAN-device JSON.

The original API documents are retained verbatim under ``source_payloads``.
Normalized indexes are convenience views; they never replace source fields.
Connections are emitted only when a relationship field explicitly points to a
known node/interface/device. MAC addresses are not used by themselves to guess
that two devices are connected.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

RELATION_TOKENS = (
    "parent", "uplink", "peer", "connect", "link", "target", "remote",
    "via", "upstream", "downstream", "neighbor", "neighbour", "gateway",
)
REFERENCE_KEYS = {
    "parent_uid", "parent_node_uid", "parent_id", "parent_device_id",
    "uplink_node_uid", "uplink_uid", "uplink_id", "connected_to_uid",
    "connected_node_uid", "via_node_uid", "peer_uid", "peer_node_uid",
    "target_uid", "target_node_uid", "remote_uid", "remote_node_uid",
    "upstream_uid", "upstream_node_uid", "neighbor_uid", "neighbour_uid",
    "parent_mac_address", "uplink_mac_address", "peer_mac_address",
    "connected_to_mac_address", "target_mac_address", "remote_mac_address",
}


def normalize_mac(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = value.strip().replace(":", "").replace("-", "").replace(".", "")
    if len(compact) != 12 or any(ch not in "0123456789abcdefABCDEF" for ch in compact):
        return None
    compact = compact.upper()
    return ":".join(compact[i:i + 2] for i in range(0, 12, 2))


def _first(mapping: dict, *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _flatten_values(value: Any, path: str = "$", out: list | None = None) -> list:
    """Record every JSON leaf/path for searchable diagnostics without losing raw JSON."""
    if out is None:
        out = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            out.append({"path": child_path, "key": str(key), "value_type": type(child).__name__})
            _flatten_values(child, child_path, out)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _flatten_values(child, f"{path}[{index}]", out)
    return out


def build_shared_mesh_model(
    mesh_payload: Any,
    landevice_payload: Any = None,
    merged_devices: list[dict] | None = None,
) -> dict:
    """Build the combined, lossless model from both FRITZ!Box JSON responses.

    ``mesh_payload`` is the ``schema_version``/``nodes`` mesh document.
    ``landevice_payload`` is the full ``/api/v0/generic/landevice`` response.
    ``merged_devices`` optionally includes TR-064/WLAN enrichment already merged
    by the integration. All of those source records are preserved as well.
    """
    mesh = mesh_payload if isinstance(mesh_payload, dict) else {}
    lan_json = landevice_payload if isinstance(landevice_payload, dict) else {}
    raw_nodes = _as_list(mesh.get("nodes"))
    raw_lan_devices = _as_list(lan_json.get("landevice"))

    model: dict[str, Any] = {
        "schema_version": mesh.get("schema_version"),
        "source_payloads": {
            "mesh_topology": deepcopy(mesh),
            "landevice": deepcopy(lan_json),
            "merged_device_records": deepcopy(merged_devices or []),
        },
        "source_schemas": {
            "mesh_topology": _flatten_values(mesh),
            "landevice": _flatten_values(lan_json),
        },
        "nodes": {},
        "interfaces": {},
        "devices": {},
        "links": [],
        "unresolved_links": [],
        "counts": {},
    }

    node_ref_index: dict[str, str] = {}
    interface_ref_index: dict[str, str] = {}
    interface_mac_index: dict[str, list[str]] = {}

    def ensure_device(mac: str | None) -> dict | None:
        if not mac:
            return None
        return model["devices"].setdefault(mac, {
            "mac": mac,
            "mesh_node_uids": [],
            "mesh_interface_uids": [],
            "landevice_records": [],
            "merged_records": [],
            "sources": [],
        })

    # 1. Full mesh graph: all node and interface fields retained under raw.
    for index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            continue
        source_uid = str(_first(raw_node, "uid", "id") or f"node-index-{index}")
        uid = source_uid
        suffix = 2
        while uid in model["nodes"]:
            uid = f"{source_uid}#{suffix}"
            suffix += 1
        device_mac = normalize_mac(_first(raw_node, "device_mac_address", "device_mac", "mac_address"))
        device_id = _first(raw_node, "device_id", "device_id_string")
        node = {
            "uid": uid,
            "source_uid": source_uid,
            "device_mac_address": device_mac,
            "device_id": deepcopy(device_id),
            "mesh_role": _first(raw_node, "mesh_role", "role"),
            "name": _first(raw_node, "name", "device_name", "friendly_name", "hostname"),
            "interfaces": [],
            "raw": deepcopy(raw_node),
        }
        model["nodes"][uid] = node
        for ref in (source_uid, uid, device_id, device_mac):
            if ref not in (None, ""):
                node_ref_index[str(ref).strip().upper()] = uid
        dev = ensure_device(device_mac)
        if dev is not None:
            dev["mesh_node_uids"].append(uid)
            dev["mesh_role"] = node["mesh_role"]
            dev["mesh_node_name"] = node["name"]
            dev["mesh_raw_node"] = deepcopy(raw_node)
            if "mesh_topology" not in dev["sources"]:
                dev["sources"].append("mesh_topology")

        for int_index, raw_int in enumerate(_as_list(raw_node.get("node_interfaces"))):
            if not isinstance(raw_int, dict):
                continue
            int_source_uid = str(_first(raw_int, "uid", "id") or f"{uid}-interface-{int_index}")
            int_uid = int_source_uid
            int_suffix = 2
            while int_uid in model["interfaces"]:
                int_uid = f"{int_source_uid}#{int_suffix}"
                int_suffix += 1
            int_mac = normalize_mac(_first(raw_int, "mac_address", "mac", "device_mac_address"))
            interface = {
                "uid": int_uid,
                "source_uid": int_source_uid,
                "node_uid": uid,
                "name": _first(raw_int, "name", "interface_name"),
                "type": _first(raw_int, "type", "interface_type"),
                "mac_address": int_mac,
                "raw": deepcopy(raw_int),
            }
            model["interfaces"][int_uid] = interface
            node["interfaces"].append(int_uid)
            for ref in (int_source_uid, int_uid):
                interface_ref_index[str(ref).strip().upper()] = int_uid
            if int_mac:
                interface_mac_index.setdefault(int_mac, []).append(int_uid)
                int_dev = ensure_device(int_mac)
                if int_dev is not None and int_uid not in int_dev["mesh_interface_uids"]:
                    int_dev["mesh_interface_uids"].append(int_uid)
                if int_dev is not None and "mesh_topology" not in int_dev["sources"]:
                    int_dev["sources"].append("mesh_topology")

    # 2. Preserve every record from the second JSON document and index by MAC.
    for index, raw_device in enumerate(raw_lan_devices):
        if not isinstance(raw_device, dict):
            continue
        mac = normalize_mac(raw_device.get("mac"))
        dev = ensure_device(mac)
        record = {"index": index, "mac": mac, "raw": deepcopy(raw_device)}
        if dev is not None:
            dev["landevice_records"].append(record)
            if "landevice" not in dev["sources"]:
                dev["sources"].append("landevice")
            for key, value in raw_device.items():
                if key not in {"mac", "iplist"}:
                    dev.setdefault("landevice_fields", {})[key] = deepcopy(value)
            # Keep normalized IP entries alongside, not instead of, raw iplist.
            dev.setdefault("ip_addresses", [])
            for container in _as_list(raw_device.get("iplist")):
                if not isinstance(container, dict):
                    continue
                entries = container.get("entry", [])
                if isinstance(entries, dict):
                    entries = [entries]
                for entry in _as_list(entries):
                    if isinstance(entry, dict) and entry.get("ip"):
                        ip_record = {
                            "address": str(entry["ip"]),
                            "type": str(entry.get("addrtype", "unknown")),
                            "raw": deepcopy(entry),
                        }
                        if ip_record not in dev["ip_addresses"]:
                            dev["ip_addresses"].append(ip_record)

    # 3. Keep the final merged device records (including TR-064/WLAN/vendor/overrides).
    for index, record in enumerate(merged_devices or []):
        if not isinstance(record, dict):
            continue
        mac = normalize_mac(record.get("mac"))
        dev = ensure_device(mac)
        if dev is None:
            continue
        dev["merged_records"].append({"index": index, "raw": deepcopy(record)})
        if "merged_device_list" not in dev["sources"]:
            dev["sources"].append("merged_device_list")
        # Add convenience fields only if not already supplied by the more raw source.
        for key, value in record.items():
            if key not in {"mac", "raw_landevice", "mesh_interfaces"}:
                dev.setdefault("merged_fields", {})[key] = deepcopy(value)

    # 4. Parse FRITZ!Box's actual topology edges. The API stores these under
    # each interface's ``node_links`` list, with both endpoint node and interface UIDs.
    # This is authoritative topology data; no MAC/name-based inference is involved.
    seen_link_ids: set[str] = set()
    for node in model["nodes"].values():
        for int_uid in node["interfaces"]:
            interface = model["interfaces"][int_uid]
            raw_links = interface["raw"].get("node_links", [])
            for raw_link in _as_list(raw_links):
                if not isinstance(raw_link, dict):
                    continue
                node_1_ref = _first(raw_link, "node_1_uid")
                node_2_ref = _first(raw_link, "node_2_uid")
                node_1 = node_ref_index.get(str(node_1_ref).strip().upper()) if node_1_ref is not None else None
                node_2 = node_ref_index.get(str(node_2_ref).strip().upper()) if node_2_ref is not None else None
                int_1_ref = _first(raw_link, "node_interface_1_uid")
                int_2_ref = _first(raw_link, "node_interface_2_uid")
                int_1 = interface_ref_index.get(str(int_1_ref).strip().upper()) if int_1_ref is not None else None
                int_2 = interface_ref_index.get(str(int_2_ref).strip().upper()) if int_2_ref is not None else None
                link_id = str(_first(raw_link, "uid", "id") or "")
                if link_id and link_id in seen_link_ids:
                    continue
                # Keep incomplete references visible for diagnosis, but only count a
                # topology edge when both endpoint nodes resolve to known mesh nodes.
                if not node_1 or not node_2:
                    model["unresolved_links"].append({
                        "source_node": node["uid"], "source_object_type": "interface",
                        "source_object_uid": int_uid, "source_field": "node_links",
                        "target_value": deepcopy(raw_link),
                    })
                    continue
                if node_1 == node_2:
                    continue
                model["links"].append({
                    "uid": link_id or None,
                    "source": node_1,
                    "target": node_2,
                    "type": _first(raw_link, "type") or interface.get("type"),
                    "state": _first(raw_link, "state"),
                    "source_interface": int_1,
                    "target_interface": int_2,
                    "source_interface_ref": int_1_ref,
                    "target_interface_ref": int_2_ref,
                    "learned_via_lldp": raw_link.get("learned_via_lldp"),
                    "source_object_type": "interface",
                    "source_object_uid": int_uid,
                    "source_field": "node_links",
                    "target_kind": "node",
                    "evidence": "fritzbox_node_links",
                    "raw": deepcopy(raw_link),
                })
                if link_id:
                    seen_link_ids.add(link_id)

    # 5. Resolve other explicitly named relationships wherever they occur in a node or interface.
    # The complete raw objects remain available even for fields not recognized here.
    seen: set[tuple[str, str, str, str]] = set()
    for node in model["nodes"].values():
        objects = [("node", node["uid"], node["raw"])]
        objects.extend(("interface", int_uid, model["interfaces"][int_uid]["raw"]) for int_uid in node["interfaces"])
        for object_type, object_uid, raw_obj in objects:
            for field, value in _walk_relation_fields(raw_obj):
                values = value if isinstance(value, list) else [value]
                for target_value in values:
                    if isinstance(target_value, dict):
                        target_value = _first(target_value, "uid", "id", "device_id", "mac_address", "mac")
                    if target_value in (None, "") or isinstance(target_value, (dict, list)):
                        continue
                    text_value = str(target_value).strip().upper()
                    target_node = node_ref_index.get(text_value)
                    target_interface = interface_ref_index.get(text_value)
                    target_mac = normalize_mac(text_value)
                    if target_node and target_node != node["uid"]:
                        target_uid, target_kind = target_node, "node"
                    elif target_interface and model["interfaces"][target_interface]["node_uid"] != node["uid"]:
                        target_uid, target_kind = model["interfaces"][target_interface]["node_uid"], "interface"
                    elif target_mac and target_mac in node_ref_index:
                        target_uid, target_kind = node_ref_index[target_mac], "device_mac"
                    else:
                        model["unresolved_links"].append({
                            "source_node": node["uid"], "source_object_type": object_type,
                            "source_object_uid": object_uid, "source_field": field,
                            "target_value": deepcopy(target_value),
                        })
                        continue
                    if target_uid == node["uid"]:
                        continue
                    signature = (node["uid"], target_uid, field, target_kind)
                    if signature not in seen:
                        model["links"].append({
                            "source": node["uid"], "target": target_uid,
                            "type": field, "source_object_type": object_type,
                            "source_object_uid": object_uid, "source_field": field,
                            "target_kind": target_kind,
                            "evidence": "explicit_reference_in_raw_json",
                        })
                        seen.add(signature)

    model["counts"] = {
        "mesh_nodes": len(model["nodes"]),
        "mesh_interfaces": len(model["interfaces"]),
        "indexed_devices": len(model["devices"]),
        "landevice_records": len(raw_lan_devices),
        "merged_device_records": len(merged_devices or []),
        "explicit_links": len(model["links"]),
        "unresolved_explicit_references": len(model["unresolved_links"]),
    }
    return model


def _walk_relation_fields(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            normalized = str(key).lower().replace("-", "_")
            if normalized != "node_links" and (normalized in REFERENCE_KEYS or any(token in normalized for token in RELATION_TOKENS)):
                # Avoid treating generic 'connection_speed'/'link_quality' metrics as endpoints.
                if isinstance(child, (str, int, float, list, dict)) and child not in (None, ""):
                    if not any(metric in normalized for metric in ("speed", "rate", "quality", "signal", "channel", "band", "status", "type", "state")):
                        yield path, child
            yield from _walk_relation_fields(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_relation_fields(child, f"{prefix}[{index}]")



def validate_mesh_topology(mesh_payload: Any) -> dict:
    """Validate every explicit node_links edge against node/interface ownership.

    This is diagnostic only: it does not alter or infer topology.
    """
    mesh = mesh_payload if isinstance(mesh_payload, dict) else {}
    raw_nodes = _as_list(mesh.get("nodes"))
    nodes: dict[str, dict] = {}
    interfaces: dict[str, dict] = {}
    for node in raw_nodes:
        if not isinstance(node, dict) or node.get("uid") in (None, ""):
            continue
        node_uid = str(node["uid"])
        nodes[node_uid] = node
        for interface in _as_list(node.get("node_interfaces")):
            if isinstance(interface, dict) and interface.get("uid") not in (None, ""):
                interfaces[str(interface["uid"])] = {"node_uid": node_uid, "raw": interface}

    seen_ids: set[str] = set()
    seen_edges: set[tuple[str, str, str, str]] = set()
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    duplicate_ids = 0
    duplicate_edges = 0
    missing_node_refs = 0
    missing_interface_refs = 0
    interface_owner_mismatches = 0
    self_links = 0
    problems: list[dict] = []
    unique_links = 0

    for parent_node in raw_nodes:
        if not isinstance(parent_node, dict):
            continue
        for parent_interface in _as_list(parent_node.get("node_interfaces")):
            if not isinstance(parent_interface, dict):
                continue
            for link in _as_list(parent_interface.get("node_links")):
                if not isinstance(link, dict):
                    continue
                link_id = str(_first(link, "uid", "id") or "")
                n1 = str(link.get("node_1_uid") or "")
                n2 = str(link.get("node_2_uid") or "")
                i1 = str(link.get("node_interface_1_uid") or "")
                i2 = str(link.get("node_interface_2_uid") or "")
                state = str(link.get("state") or "UNKNOWN").upper()
                link_type = str(link.get("type") or "UNKNOWN").upper()
                status_counts[state] = status_counts.get(state, 0) + 1
                type_counts[link_type] = type_counts.get(link_type, 0) + 1
                if link_id and link_id in seen_ids:
                    duplicate_ids += 1
                elif link_id:
                    seen_ids.add(link_id)
                edge = tuple(sorted((n1, n2))) + tuple(sorted((i1, i2)))
                if edge in seen_edges:
                    duplicate_edges += 1
                else:
                    seen_edges.add(edge)
                    unique_links += 1

                reasons = []
                if not n1 or not n2 or n1 not in nodes or n2 not in nodes:
                    missing_node_refs += 1
                    reasons.append("missing_node_reference")
                if not i1 or not i2 or i1 not in interfaces or i2 not in interfaces:
                    missing_interface_refs += 1
                    reasons.append("missing_interface_reference")
                if i1 in interfaces and n1 in nodes and interfaces[i1]["node_uid"] != n1:
                    interface_owner_mismatches += 1
                    reasons.append("interface_1_owner_mismatch")
                if i2 in interfaces and n2 in nodes and interfaces[i2]["node_uid"] != n2:
                    interface_owner_mismatches += 1
                    reasons.append("interface_2_owner_mismatch")
                if n1 and n1 == n2:
                    self_links += 1
                    reasons.append("self_link")
                # The enclosing interface must be one of the edge endpoints.
                parent_node_uid = str(parent_node.get("uid") or "")
                parent_interface_uid = str(parent_interface.get("uid") or "")
                if parent_interface_uid and parent_interface_uid not in (i1, i2):
                    reasons.append("link_not_attached_to_enclosing_interface")
                if reasons and len(problems) < 25:
                    problems.append({"link_uid": link_id or None, "state": state, "type": link_type,
                                     "node_1_uid": n1, "node_2_uid": n2,
                                     "interface_1_uid": i1, "interface_2_uid": i2,
                                     "enclosing_node_uid": parent_node_uid,
                                     "enclosing_interface_uid": parent_interface_uid,
                                     "problems": reasons})

    return {
        "nodes_indexed": len(nodes),
        "interfaces_indexed": len(interfaces),
        "raw_link_records": sum(len(_as_list(i.get("node_links"))) for n in raw_nodes if isinstance(n, dict) for i in _as_list(n.get("node_interfaces")) if isinstance(i, dict)),
        "unique_link_edges": unique_links,
        "duplicate_link_ids": duplicate_ids,
        "duplicate_edge_records": duplicate_edges,
        "states": status_counts,
        "types": type_counts,
        "missing_node_reference_records": missing_node_refs,
        "missing_interface_reference_records": missing_interface_refs,
        "interface_owner_mismatch_count": interface_owner_mismatches,
        "self_link_records": self_links,
        "problem_samples": problems,
    }

def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _mesh_client_radio_data(shared: dict, model: dict) -> dict:
    """Extract radio metrics from every WLAN uplink interface of a mesh node.

    FRITZ!Box exposes a repeater's uplink signal on the repeater-side
    ``UPLINK:2G`` / ``UPLINK:5G`` interfaces. The device MAC in the LAN list
    can be an alias (for example LANBridge), so using only the interface MACs
    attached to that alias misses the actual radio interfaces. Resolve the
    canonical mesh node first and walk all of its interfaces.
    """
    result: dict[str, Any] = {}
    interfaces = model.get("interfaces", {})
    nodes = model.get("nodes", {})
    node_uids = list(shared.get("mesh_node_uids", []))

    # Include every interface belonging to the canonical node, regardless of
    # which interface MAC was used by the LAN-device record or override.
    node_interfaces: list[tuple[str, dict, dict]] = []
    for node_uid in node_uids:
        node = nodes.get(node_uid)
        if not isinstance(node, dict):
            continue
        for interface_uid in node.get("interfaces", []):
            interface = interfaces.get(interface_uid)
            if not isinstance(interface, dict):
                continue
            raw_interface = interface.get("raw", {})
            if str(raw_interface.get("type", interface.get("type", ""))).upper() != "WLAN":
                continue
            node_interfaces.append((node_uid, interface, raw_interface))

    # Keep a separate best link for each band. Prefer an explicit UPLINK
    # interface and a connected link to the mesh master. Other client links
    # on AP interfaces must not overwrite the repeater's backhaul signal.
    for band, prefixes in (("wifi_2_4", ("UPLINK:2G", "UPLINK:2.4G")),
                           ("wifi_5", ("UPLINK:5G",))):
        candidates: list[tuple[int, float, dict, dict, dict]] = []
        for node_uid, interface, raw_interface in node_interfaces:
            name = str(raw_interface.get("name", interface.get("name", ""))).upper()
            channel = _number(raw_interface.get("current_channel"))
            if name.startswith(prefixes):
                band_match = True
                priority = 2
            elif name.startswith("UPLINK") and channel is not None:
                band_match = (1 <= channel <= 14) if band == "wifi_2_4" else channel >= 32
                priority = 1
            else:
                # Do not use AP interfaces: their node_links describe clients
                # connected to the repeater, not the repeater's uplink.
                continue
            if not band_match:
                continue
            for link in raw_interface.get("node_links", []) if isinstance(raw_interface.get("node_links", []), list) else []:
                if not isinstance(link, dict) or str(link.get("state", "")).upper() != "CONNECTED":
                    continue
                n1, n2 = str(link.get("node_1_uid") or ""), str(link.get("node_2_uid") or "")
                if node_uid not in (n1, n2):
                    continue
                peer_uid = n2 if n1 == node_uid else n1
                peer = nodes.get(peer_uid, {})
                peer_is_master = str(peer.get("mesh_role") or "").strip().lower() == "master"
                last_connected = _number(link.get("last_connected")) or -1
                candidates.append((priority + (10 if peer_is_master else 0), last_connected, interface, raw_interface, link))

        # Compatibility fallback for ordinary WLAN clients: their FRITZ!Box
        # payload commonly exposes the association on an AP/peer interface
        # with current_channel, but without an UPLINK-named interface.
        if not candidates:
            for node_uid, interface, raw_interface in node_interfaces:
                channel = _number(raw_interface.get("current_channel"))
                if channel is None:
                    continue
                channel_matches = (1 <= channel <= 14) if band == "wifi_2_4" else channel >= 32
                if not channel_matches:
                    continue
                for link in raw_interface.get("node_links", []) if isinstance(raw_interface.get("node_links", []), list) else []:
                    if isinstance(link, dict) and str(link.get("state", "")).upper() == "CONNECTED":
                        candidates.append((0, _number(link.get("last_connected")) or -1, interface, raw_interface, link))
        if not candidates:
            continue
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _, _, interface, raw_interface, link = candidates[0]
        result[f"{band}_signal_rx_dbm"] = _number(link.get("rx_rcpi"))
        result[f"{band}_signal_tx_dbm"] = _number(link.get("tx_rcpi"))
        channel = _number(raw_interface.get("current_channel"))
        if channel is not None:
            result[f"{band}_channel"] = int(channel)
        info = raw_interface.get("current_channel_info")
        width = info.get("channel_width") if isinstance(info, dict) else None
        if isinstance(width, str):
            digits = "".join(ch for ch in width if ch.isdigit())
            width_value = int(digits) if digits else None
        else:
            width_value = _number(width)
        if width_value is not None:
            result[f"{band}_channel_width"] = width_value
        rates = [_number(link.get("cur_data_rate_rx")), _number(link.get("cur_data_rate_tx"))]
        rates = [rate for rate in rates if rate is not None and rate >= 0]
        if rates:
            result[f"{band}_speed_mbps"] = round(max(rates) / 1000, 1)
        if "mesh_wifi_link_uid" not in result:
            node_uid = str(interface.get("node_uid") or "")
            n1, n2 = str(link.get("node_1_uid") or ""), str(link.get("node_2_uid") or "")
            result["mesh_wifi_interface_uid"] = interface.get("uid")
            result["mesh_wifi_link_uid"] = link.get("uid")
            result["mesh_wifi_link_state"] = link.get("state")
            result["mesh_wifi_access_node_uid"] = n2 if n1 == node_uid else n1

    # Keep the legacy generic fields populated from the best available band.
    for band in ("wifi_5", "wifi_2_4"):
        if result.get(f"{band}_speed_mbps") is not None:
            result["wifi_speed_mbps"] = result[f"{band}_speed_mbps"]
            result["mesh_wifi_band"] = "5 GHz" if band == "wifi_5" else "2.4 GHz"
            break
    return result


def _direct_mesh_connections(model: dict) -> dict[str, list[dict]]:
    """Return explicit FRITZ!Box mesh neighbours indexed by endpoint MAC.

    Multiple radio links (for example 2.4 and 5 GHz) between the same two
    mesh nodes are one device-to-device relationship. For a mesh slave that
    has an explicit link to the mesh master, the master is the reported parent;
    parallel/secondary observations do not create a false "multiple parents"
    result. Raw links remain untouched in ``model["links"]``.
    """
    nodes = model.get("nodes", {}) if isinstance(model, dict) else {}
    interfaces = model.get("interfaces", {}) if isinstance(model, dict) else {}
    links = model.get("links", []) if isinstance(model, dict) else {}

    node_info: dict[str, dict] = {}
    for uid, node in nodes.items():
        mac = normalize_mac(node.get("device_mac_address"))
        if not mac:
            continue
        raw = node.get("raw", {}) if isinstance(node.get("raw"), dict) else {}
        node_info[uid] = {
            "mac": mac,
            "name": (raw.get("device_friendly_name")
                     or raw.get("device_name_lldp")
                     or node.get("name") or mac),
            "role": str(node.get("mesh_role") or "").strip().lower(),
        }

    # First collect all explicit, connected edges by local node and neighbour
    # node. Interface-level parallel links are retained as details, not as
    # separate parent devices.
    grouped: dict[str, dict[str, dict]] = {}
    for link in links:
        if not isinstance(link, dict) or str(link.get("state") or "").upper() != "CONNECTED":
            continue
        source_uid, target_uid = link.get("source"), link.get("target")
        source, target = node_info.get(source_uid), node_info.get(target_uid)
        if not source or not target:
            continue
        source_int = interfaces.get(link.get("source_interface"), {})
        target_int = interfaces.get(link.get("target_interface"), {})
        for own_uid, own, neighbour, own_int, neighbour_int in (
            (source_uid, source, target, source_int, target_int),
            (target_uid, target, source, target_int, source_int),
        ):
            neighbour_mac = neighbour["mac"]
            bucket = grouped.setdefault(own["mac"], {})
            item = bucket.setdefault(neighbour_mac, {
                "neighbour_mac": neighbour_mac,
                "neighbour_name": neighbour["name"],
                "neighbour_mesh_role": neighbour["role"],
                "link_uids": [],
                "link_types": [],
                "local_interfaces": [],
                "neighbour_interfaces": [],
                "links": [],
                "evidence": "FRITZ!Box node_links",
            })
            detail = {
                "link_uid": link.get("uid"),
                "link_type": link.get("type"),
                "state": link.get("state"),
                "learned_via_lldp": link.get("learned_via_lldp"),
                "local_interface": own_int.get("name"),
                "neighbour_interface": neighbour_int.get("name"),
                "rate_rx_kbit_s": (link.get("raw") or {}).get("cur_data_rate_rx"),
                "rate_tx_kbit_s": (link.get("raw") or {}).get("cur_data_rate_tx"),
            }
            signature = (detail["link_uid"], detail["local_interface"], detail["neighbour_interface"])
            seen_signatures = item.setdefault("_seen", set())
            if signature not in seen_signatures:
                seen_signatures.add(signature)
                item["links"].append(detail)
            if detail["link_uid"] and detail["link_uid"] not in item["link_uids"]:
                item["link_uids"].append(detail["link_uid"])
            if detail["link_type"] and detail["link_type"] not in item["link_types"]:
                item["link_types"].append(detail["link_type"])
            for field, value in (("local_interfaces", detail["local_interface"]),
                                 ("neighbour_interfaces", detail["neighbour_interface"])):
                if value and value not in item[field]:
                    item[field].append(value)

    result: dict[str, list[dict]] = {}
    for own_uid, own in node_info.items():
        neighbours = list(grouped.get(own["mac"], {}).values())
        # For mesh repeaters, prefer the explicitly linked mesh master as the
        # parent. This is based on FRITZ!Box mesh_role, never on names or MACs.
        if own["role"] == "slave":
            masters = [item for item in neighbours if item.get("neighbour_mesh_role") == "master"]
            if masters:
                neighbours = masters
        for item in neighbours:
            item.pop("_seen", None)
        if neighbours:
            result[own["mac"]] = neighbours
    return result


def merge_switch_observations(model: dict, devices: list[dict], switch_configs: list[dict], observations_by_mac: dict[str, list[dict]], errors: dict[str, str] | None = None) -> dict:
    """Merge SNMP switch inventory and MAC-table observations into the shared model.

    FDB entries are observations, not proof of direct physical adjacency: a port
    may lead to another switch. Preserve all observations and their provenance.
    """
    if not isinstance(model, dict):
        model = {}
    model.setdefault("switches", {})
    model.setdefault("switch_mac_table", {})
    model.setdefault("switch_errors", {})
    model.setdefault("switch_links", [])
    for config in switch_configs or []:
        host = str(config.get("host", "")).strip()
        if host:
            model["switches"][host] = {"key": host, "name": config.get("name") or host, "host": host, "port": int(config.get("port", 161)), "protocol": "SNMPv3", "raw_config": deepcopy(config)}
    normalized: dict[str, list[dict]] = {}
    for raw_mac, entries in (observations_by_mac or {}).items():
        mac = normalize_mac(raw_mac)
        if not mac:
            continue
        items = [deepcopy(item) for item in entries if isinstance(item, dict)]
        if not items:
            continue
        normalized[mac] = items
        model["switch_mac_table"][mac] = items
        shared = model.setdefault("devices", {}).setdefault(mac, {"mac": mac, "mesh_node_uids": [], "mesh_interface_uids": [], "landevice_records": [], "merged_records": [], "sources": []})
        shared["switch_observations"] = deepcopy(items)
        if "snmp_switch" not in shared.setdefault("sources", []):
            shared["sources"].append("snmp_switch")
    model["switch_errors"] = deepcopy(errors or {})

    # A port that learns several different MAC addresses is a shared segment
    # (typically an uplink to another switch, router, AP or bridge). Its FDB
    # entries must not be turned into direct endpoint-to-switch connections.
    port_macs: dict[tuple[str, str], set[str]] = {}
    for observed_mac, items in normalized.items():
        for item in items:
            switch_host = str(item.get("switch_host") or "").strip().lower()
            switch_port = str(item.get("switch_port") or "").strip().lower()
            if switch_host and switch_port:
                port_macs.setdefault((switch_host, switch_port), set()).add(observed_mac)

    model["switch_port_mac_counts"] = {
        f"{host}|{port}": len(macs) for (host, port), macs in port_macs.items()
    }
    model["switch_links"] = [
        {
            "mac": mac,
            "switch_host": item.get("switch_host"),
            "switch_name": item.get("switch_name"),
            "switch_port": item.get("switch_port"),
            "switch_bridge_port": item.get("switch_bridge_port"),
            "switch_if_index": item.get("switch_if_index"),
            "learned_mac_count_on_port": len(port_macs.get((
                str(item.get("switch_host") or "").strip().lower(),
                str(item.get("switch_port") or "").strip().lower(),
            ), set())),
            "evidence": "SNMPv3 BRIDGE-MIB FDB",
            "relationship": "shared_port_uplink_or_uncertain" if len(port_macs.get((
                str(item.get("switch_host") or "").strip().lower(),
                str(item.get("switch_port") or "").strip().lower(),
            ), set())) > 1 else "single_mac_learned_port_candidate_not_proven_direct",
        }
        for mac, items in normalized.items() for item in items
    ]
    for device in devices or []:
        if not isinstance(device, dict):
            continue
        mac = normalize_mac(device.get("mac"))
        if not mac:
            continue

        # A switch FDB also learns Wi-Fi clients behind an access point. That
        # only identifies the AP/uplink path, not a direct wired connection
        # for the client. Keep the raw observation in switch_mac_table, but
        # deliberately exclude WLAN clients from per-device switch links.
        role = str(device.get("device_role") or "").strip().lower()
        mesh_role = str(device.get("mesh_role") or "").strip().lower()
        device_type = str(device.get("device_type") or "").strip().lower()
        model_name = " ".join(str(device.get(key) or "") for key in ("model", "friendly_name", "name")).lower()
        interface = str(device.get("interface_type") or device.get("connection_type") or "").strip().lower()
        # A FRITZ!Repeater may have WLAN-Client in the user override because
        # its uplink is wireless. Its mesh node identity still makes it
        # infrastructure, not an ordinary WLAN endpoint behind the switch.
        is_infrastructure_node = (
            role in {"mesh-master", "repeater"}
            or mesh_role in {"master", "slave", "mesh-master", "repeater"}
            or device_type in {"repeater", "mesh-repeater", "mesh-master"}
            or "fritz!repeater" in model_name
        )
        is_wlan_client = role == "wlan-client" or (
            not is_infrastructure_node
            and (
                interface in {"802.11", "wlan", "wifi", "wi-fi", "wireless"}
                or device.get("wifi_channel") is not None
                or device.get("wifi_speed_mbps") is not None
                or any(device.get(key) is not None for key in (
                    "wifi_2_4_channel", "wifi_5_channel",
                    "wifi_2_4_speed_mbps", "wifi_5_speed_mbps",
                ))
            )
        )

        # A downstream Ethernet switch is infrastructure, but unlike a
        # wireless repeater its own management MAC learned on an upstream
        # switch port identifies the switch-to-switch uplink. Other MACs on
        # that same port are expected: they belong to devices behind it.
        # Detect common switch naming/model conventions as well as explicit
        # user classifications so this also works when FRITZ!Box calls it
        # merely "LAN-Client" and has no device type.
        # Device class comes from the integration's normal classification
        # pipeline, where an explicit device_overrides.csv entry is applied.
        # Never infer a switch from vendor/model/hostname strings here.
        is_switch_node = "switch" in role or "switch" in device_type

        # Wireless endpoints and FRITZ!Box mesh infrastructure still must
        # not be mapped from a learned MAC-table entry. A downstream switch
        # is the deliberate exception: its own MAC is the endpoint of the
        # upstream switch port even when that port also learns downstream
        # devices.
        exclude_switch_mapping = is_wlan_client or (
            is_infrastructure_node and not is_switch_node
        )
        raw_matches = normalized.get(mac, [])
        matches = []
        shared_port_matches = []
        if not exclude_switch_mapping:
            for item in raw_matches:
                port_key = (
                    str(item.get("switch_host") or "").strip().lower(),
                    str(item.get("switch_port") or "").strip().lower(),
                )
                count = len(port_macs.get(port_key, set()))
                if count == 1 or is_switch_node:
                    matches.append({**item, "learned_mac_count_on_port": count})
                elif count > 1:
                    shared_port_matches.append({**item, "learned_mac_count_on_port": count})
        device["switch_connections"] = deepcopy(matches)
        if exclude_switch_mapping:
            # Avoid retaining stale values if role/type changes between scans.
            device["switch_name"] = None
            device["switch_port"] = None
            if is_infrastructure_node:
                device["switch_connection_excluded_reason"] = (
                    "Mesh-Infrastruktur: direkte Verbindung wird aus Mesh-Daten ermittelt"
                )
            else:
                device["switch_connection_excluded_reason"] = (
                    "WLAN-Client: kein direkter Ethernet-Anschluss"
                )
        elif shared_port_matches and not matches:
            device["switch_name"] = None
            device["switch_port"] = None
            device["switch_connection_excluded_reason"] = (
                "Switch-Port lernt mehrere MAC-Adressen: Uplink/shared segment, kein Direktanschluss-Nachweis"
            )
            device["switch_uplink_observations"] = deepcopy(shared_port_matches)
        else:
            device.pop("switch_connection_excluded_reason", None)
            device.pop("switch_uplink_observations", None)
            if len(matches) == 1:
                device.update(matches[0])
            elif len(matches) > 1:
                device["switch_name"] = "Mehrere Switches"
                device["switch_port"] = None
        shared = model.get("devices", {}).get(mac)
        if shared is not None and matches:
            shared["switch_observations"] = deepcopy(matches)
    return model

def enrich_device_records(devices: list[dict], model: dict) -> list[dict]:
    """Merge mesh-derived WLAN fields and explicit direct neighbours into devices."""
    by_mac = model.get("devices", {}) if isinstance(model, dict) else {}
    direct_by_mac = _direct_mesh_connections(model if isinstance(model, dict) else {})
    nodes = model.get("nodes", {}) if isinstance(model, dict) else {}
    interfaces = model.get("interfaces", {}) if isinstance(model, dict) else {}

    def resolve_mesh_node(mac: str | None):
        """Resolve a LAN-list MAC through any interface MAC of a mesh node."""
        if not mac:
            return None, None
        direct_shared = by_mac.get(mac)
        if direct_shared and direct_shared.get("mesh_node_uids"):
            node_uid = direct_shared["mesh_node_uids"][0]
            return direct_shared, nodes.get(node_uid)
        interface_shared = by_mac.get(mac)
        interface_uids = interface_shared.get("mesh_interface_uids", []) if interface_shared else []
        for interface_uid in interface_uids:
            interface = interfaces.get(interface_uid, {})
            node_uid = interface.get("node_uid")
            node = nodes.get(node_uid)
            if node:
                node_mac = normalize_mac(node.get("device_mac_address"))
                canonical_shared = by_mac.get(node_mac) if node_mac else None
                if canonical_shared:
                    return canonical_shared, node
        # Also support a node/interface MAC that has no standalone shared
        # device record for any reason.
        for node in nodes.values():
            if normalize_mac(node.get("device_mac_address")) == mac:
                return by_mac.get(mac), node
            for interface_uid in node.get("interfaces", []):
                interface = interfaces.get(interface_uid, {})
                if normalize_mac(interface.get("mac_address")) == mac:
                    node_mac = normalize_mac(node.get("device_mac_address"))
                    return by_mac.get(node_mac) if node_mac else None, node
        return None, None

    for device in devices:
        mac = normalize_mac(device.get("mac"))
        shared, mesh_node = resolve_mesh_node(mac)
        node_mac = normalize_mac(mesh_node.get("device_mac_address")) if mesh_node else mac
        direct = direct_by_mac.get(node_mac, []) if node_mac else []
        device["mesh_direct_connections"] = deepcopy(direct)
        device["mesh_direct_connection_source"] = "FRITZ!Box node_links" if direct else None
        if not shared:
            continue
        device["shared_device_key"] = mac
        device["mesh_node_uids"] = list(shared.get("mesh_node_uids", []))
        device["mesh_interface_uids"] = list(shared.get("mesh_interface_uids", []))
        device["mesh_role"] = shared.get("mesh_role", device.get("mesh_role"))
        device["mesh_node_name"] = shared.get("mesh_node_name") or (mesh_node.get("name") if mesh_node else None)
        if mesh_node:
            device["mesh_node_uids"] = [mesh_node.get("uid")] if mesh_node.get("uid") else device["mesh_node_uids"]
            device["mesh_role"] = mesh_node.get("mesh_role") or device.get("mesh_role")
        device["ip_addresses"] = deepcopy(shared.get("ip_addresses", device.get("ip_addresses", [])))

        # Only use mesh radio values when a field is absent from the more
        # specific TR-064 client report. Never replace a real percentage with dBm.
        radio = _mesh_client_radio_data(shared, model)
        for key, value in radio.items():
            if value is not None and device.get(key) in (None, ""):
                device[key] = value
        band = radio.get("mesh_wifi_band")
        if band == "2.4 GHz":
            for target, source in (("wifi_2_4_channel", "wifi_channel"), ("wifi_2_4_channel_width", "wifi_channel_width")):
                if device.get(target) in (None, "") and radio.get(source) is not None:
                    device[target] = radio[source]
        elif band == "5 GHz":
            for target, source in (("wifi_5_channel", "wifi_channel"), ("wifi_5_channel_width", "wifi_channel_width")):
                if device.get(target) in (None, "") and radio.get(source) is not None:
                    device[target] = radio[source]
    return devices
