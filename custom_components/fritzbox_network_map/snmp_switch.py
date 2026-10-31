"""SNMPv3 read-only access to managed switches."""
from __future__ import annotations

import json
import logging

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, UsmUserData, UdpTransportTarget, ContextData, ObjectType,
    ObjectIdentity, get_cmd, walk_cmd,
    usmHMACSHAAuthProtocol, usmHMACMD5AuthProtocol, usmHMAC192SHA256AuthProtocol,
    usmAesCfb128Protocol, usmDESPrivProtocol,
)

AUTH_PROTOCOLS = {
    "SHA": usmHMACSHAAuthProtocol,
    "SHA256": usmHMAC192SHA256AuthProtocol,
    "MD5": usmHMACMD5AuthProtocol,
}
PRIV_PROTOCOLS = {"AES": usmAesCfb128Protocol, "DES": usmDESPrivProtocol}

_LOGGER = logging.getLogger(__name__)


def _log_raw_table(switch: dict, table_name: str, payload: dict) -> None:
    """Write the complete raw SNMP table to WARNING logs in manageable chunks.

    The user explicitly enables this diagnostic by installing this version.
    Raw network details are therefore logged at WARNING without requiring DEBUG or logger configuration.
    """
    try:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        serialized = repr(payload)
    chunk_size = 5000
    chunks = [serialized[i:i + chunk_size] for i in range(0, len(serialized), chunk_size)] or [""]
    host = switch.get("host", "unknown")
    for index, chunk in enumerate(chunks, start=1):
        _LOGGER.warning(
            "SWITCH-SNMP-ROHDATEN host=%s table=%s part=%s/%s payload=%s",
            host, table_name, index, len(chunks), chunk,
        )


def _numeric_oid(oid: str) -> str:
    """Normalize pysnmp's pretty-printed numeric or symbolic OID to numeric form."""
    # pysnmp may render ObjectIdentity names symbolically, e.g.
    # SNMPv2-SMI::mib-2.17.4.3.1.2.1.216.133.172.235.12.4
    value = str(oid).split("::", 1)[-1]
    if value.startswith("mib-2."):
        value = "1.3.6.1.2.1." + value[len("mib-2."):]
    return value


def _user(config):
    return UsmUserData(
        config["username"], config["auth_password"], config["priv_password"],
        authProtocol=AUTH_PROTOCOLS[config.get("auth_protocol", "SHA")],
        privProtocol=PRIV_PROTOCOLS[config.get("priv_protocol", "AES")],
    )


async def _target(config):
    return await UdpTransportTarget.create(
        (config["host"], int(config.get("port", 161))), timeout=2, retries=1
    )


async def async_test_snmpv3(config: dict) -> str:
    engine = SnmpEngine()
    try:
        indication, status, index, binds = await get_cmd(
            engine, _user(config), await _target(config), ContextData(),
            ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0")),
        )
        if indication:
            raise RuntimeError(str(indication))
        if status:
            raise RuntimeError(str(status.prettyPrint()))
        return str(binds[0][1]) if binds else "SNMPv3 OK"
    finally:
        engine.close_dispatcher()


async def _walk(engine, user, target, oid):
    result = {}
    async for indication, status, index, binds in walk_cmd(
        engine, user, target, ContextData(), ObjectType(ObjectIdentity(oid)),
        lexicographicMode=False,
    ):
        if indication:
            raise RuntimeError(str(indication))
        if status:
            raise RuntimeError(str(status.prettyPrint()))
        for name, value in binds:
            result[name.prettyPrint()] = value
    return result


async def async_get_mac_table(config: dict) -> dict[str, dict]:
    """Return normalized MAC -> switch-port observations from bridge and VLAN FDBs."""
    engine = SnmpEngine()
    try:
        user, target = _user(config), await _target(config)
        sys_descr = await async_test_snmpv3(config)

        # Read both the classic bridge FDB and the VLAN-aware Q-BRIDGE FDB.
        # Some managed switches expose only a subset of learned MACs in the
        # classic table while the VLAN-aware table contains the full inventory.
        fdb = await _walk(engine, user, target, "1.3.6.1.2.1.17.4.3.1.2")
        qbridge_fdb = await _walk(engine, user, target, "1.3.6.1.2.1.17.7.1.2.2.1.2")
        bridge_if = await _walk(engine, user, target, "1.3.6.1.2.1.17.1.4.1.2")
        if_names = await _walk(engine, user, target, "1.3.6.1.2.1.31.1.1.1.1")

        # Log complete raw responses before normalization, including the
        # VLAN-aware table. Nothing is filtered to a single device.
        _log_raw_table(config, "BRIDGE-MIB-FDB", fdb)
        _log_raw_table(config, "Q-BRIDGE-MIB-VLAN-FDB", qbridge_fdb)
        _log_raw_table(config, "BRIDGE-MIB-PORT-TO-IFINDEX", bridge_if)
        _log_raw_table(config, "IF-MIB-IFNAME", if_names)

        bridge_to_if = {}
        for oid, value in bridge_if.items():
            try:
                numeric_oid = _numeric_oid(oid)
                bridge_port = int(numeric_oid.rsplit(".", 1)[1])
                bridge_to_if[bridge_port] = int(value)
            except (ValueError, TypeError):
                continue
        if_by_index = {}
        for oid, value in if_names.items():
            try:
                if_by_index[int(_numeric_oid(oid).rsplit(".", 1)[1])] = str(value)
            except (ValueError, TypeError):
                continue

        result = {}
        classic_prefix = "1.3.6.1.2.1.17.4.3.1.2.1."
        for oid, value in fdb.items():
            numeric_oid = _numeric_oid(oid)
            if not numeric_oid.startswith(classic_prefix):
                continue
            try:
                octets = [int(part) for part in numeric_oid[len(classic_prefix):].split(".")]
                if len(octets) != 6 or any(part < 0 or part > 255 for part in octets):
                    continue
                mac = ":".join(f"{part:02X}" for part in octets)
                bridge_port = int(value)
                if_index = bridge_to_if.get(bridge_port)
                port_name = if_by_index.get(if_index, f"Bridge-Port {bridge_port}")
                result[mac] = {
                    "switch_name": config.get("name") or config["host"],
                    "switch_host": config["host"],
                    "switch_port": port_name,
                    "switch_bridge_port": bridge_port,
                    "switch_if_index": if_index,
                    "switch_sys_descr": sys_descr,
                    "switch_data_source": "SNMPv3 BRIDGE-MIB",
                }
            except (ValueError, TypeError):
                continue

        # Q-BRIDGE dot1qTpFdbPort index = VLAN ID + six MAC octets.
        # It is VLAN-aware and therefore used to enrich/override classic FDB
        # records for the same MAC. The VLAN is retained as provenance.
        qbridge_prefix = "1.3.6.1.2.1.17.7.1.2.2.1.2."
        qbridge_count = 0
        for oid, value in qbridge_fdb.items():
            numeric_oid = _numeric_oid(oid)
            if not numeric_oid.startswith(qbridge_prefix):
                continue
            try:
                index_parts = [int(part) for part in numeric_oid[len(qbridge_prefix):].split(".")]
                if len(index_parts) != 7:
                    continue
                vlan_id, *octets = index_parts
                if not 1 <= vlan_id <= 4094 or any(part < 0 or part > 255 for part in octets):
                    continue
                mac = ":".join(f"{part:02X}" for part in octets)
                bridge_port = int(value)
                if_index = bridge_to_if.get(bridge_port)
                port_name = if_by_index.get(if_index, f"Bridge-Port {bridge_port}")
                result[mac] = {
                    "switch_name": config.get("name") or config["host"],
                    "switch_host": config["host"],
                    "switch_port": port_name,
                    "switch_bridge_port": bridge_port,
                    "switch_if_index": if_index,
                    "switch_vlan_id": vlan_id,
                    "switch_sys_descr": sys_descr,
                    "switch_data_source": "SNMPv3 Q-BRIDGE-MIB VLAN FDB",
                }
                qbridge_count += 1
            except (ValueError, TypeError):
                continue

        _log_raw_table(config, "ABGELEITETE-MAC-PORT-ZUORDNUNG", result)
        _LOGGER.info(
            "SNMP-Switch %s: Rohdaten gelesen: FDB=%d, Q-BRIDGE-FDB=%d, Bridge-Port-Zuordnungen=%d, Interface-Namen=%d, MAC-Zuordnungen=%d",
            config.get("host", "unknown"), len(fdb), qbridge_count, len(bridge_if), len(if_names), len(result),
        )
        return result
    finally:
        engine.close_dispatcher()

async def async_get_lldp_neighbors(config: dict) -> list[dict]:
    """Read LLDP local-port and remote-neighbour tables from a managed switch.

    LLDP-MIB is optional: unsupported tables return an empty list to the caller,
    without affecting the existing FDB/Mesh data sources.
    """
    engine = SnmpEngine()
    try:
        user, target = _user(config), await _target(config)
        base = "1.0.8802.1.1.2.1"
        local_desc = await _walk(engine, user, target, f"{base}.3.7.1.4")
        remote_columns = {
            "chassis_subtype": f"{base}.4.1.1.4",
            "chassis_id": f"{base}.4.1.1.5",
            "port_subtype": f"{base}.4.1.1.6",
            "port_id": f"{base}.4.1.1.7",
            "port_description": f"{base}.4.1.1.8",
            "system_name": f"{base}.4.1.1.9",
            "system_description": f"{base}.4.1.1.10",
        }
        tables = {}
        for key, oid in remote_columns.items():
            tables[key] = await _walk(engine, user, target, oid)

        def value_text(value):
            if hasattr(value, "asOctets"):
                try:
                    raw = value.asOctets()
                    try:
                        return raw.decode("utf-8").strip("\x00 ")
                    except UnicodeDecodeError:
                        return ":".join(f"{b:02X}" for b in raw)
                except Exception:
                    pass
            return str(value).strip()

        local_by_port = {}
        local_prefix = f"{base}.3.7.1.4."
        for oid, value in local_desc.items():
            numeric = _numeric_oid(oid)
            if numeric.startswith(local_prefix):
                try:
                    local_by_port[int(numeric[len(local_prefix):])] = value_text(value)
                except ValueError:
                    continue

        records = {}
        for field, table in tables.items():
            prefix = remote_columns[field] + "."
            for oid, value in table.items():
                numeric = _numeric_oid(oid)
                if not numeric.startswith(prefix):
                    continue
                try:
                    suffix = numeric[len(prefix):].split(".")
                    if len(suffix) != 3:
                        continue
                    key = tuple(int(part) for part in suffix)
                    records.setdefault(key, {})[field] = value_text(value)
                except (ValueError, TypeError):
                    continue

        result = []
        for (_time_mark, local_port_num, remote_index), fields in sorted(records.items()):
            local_name = local_by_port.get(local_port_num) or f"LLDP-Port {local_port_num}"
            result.append({
                "switch_name": config.get("name") or config.get("host"),
                "switch_host": config.get("host"),
                "local_port_num": local_port_num,
                "local_port": local_name,
                "remote_index": remote_index,
                "remote_chassis_subtype": fields.get("chassis_subtype"),
                "remote_chassis_id": fields.get("chassis_id"),
                "remote_port_subtype": fields.get("port_subtype"),
                "remote_port_id": fields.get("port_id"),
                "remote_port_description": fields.get("port_description"),
                "remote_system_name": fields.get("system_name"),
                "remote_system_description": fields.get("system_description"),
                "source": "LLDP-MIB",
                "relationship": "direct_neighbor",
            })
        _log_raw_table(config, "LLDP-NEIGHBORS-NORMALIZED", {str(i): row for i, row in enumerate(result)})
        _LOGGER.info("LLDP-Switch %s: %d direkte Nachbar-Einträge gelesen", config.get("host"), len(result))
        return result
    finally:
        engine.close_dispatcher()

