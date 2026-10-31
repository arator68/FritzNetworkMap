"""Helpers for merging FRITZ!Box device data from different sources."""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


def merge_wlan_data(
    devices: list[dict],
    wlan_devices: list[dict],
    mesh_mac_aliases: dict[str, str] | None = None,
) -> None:
    """Merge WLAN readings into band-specific fields only.

    The FRITZ!Box may report multiple radio/interface MAC addresses for one
    mesh repeater. Alias MACs are mapped to the canonical device, while
    readings from 2.4 GHz and 5 GHz are stored separately according to channel.
    Generic wifi_* fields are intentionally not populated; consumers should
    use the band-specific wifi_2_4_* and wifi_5_* fields.
    """
    by_mac = {
        str(device.get("mac", "")).strip().upper(): device
        for device in devices
    }
    aliases = {
        str(alias).strip().upper(): str(primary).strip().upper()
        for alias, primary in (mesh_mac_aliases or {}).items()
    }

    common_fields = (
        "wifi_speed_mbps",
        "wifi_signal_strength",
        "wifi_channel",
        "wifi_channel_width",
        "wifi_guest",
    )

    for wlan in wlan_devices:
        mac = str(wlan.get("mac", "")).strip().upper()
        if not mac:
            continue

        primary_mac = aliases.get(mac, mac)
        target = by_mac.get(primary_mac)
        if target is None:
            _LOGGER.debug(
                "WLAN-Datensatz ohne passendes LAN-Gerät ignoriert: MAC=%s (Ziel=%s)",
                mac,
                primary_mac,
            )
            continue

        channel = wlan.get("wifi_channel")
        try:
            band = "2_4" if channel is not None and int(channel) <= 14 else "5"
        except (TypeError, ValueError):
            band = None

        if band:
            for key in common_fields:
                value = wlan.get(key)
                if value is not None:
                    target[f"wifi_{band}_{key.removeprefix('wifi_')}"] = value

        sources = target.setdefault(
            "sources", [target.get("source", "fritzbox_landevice")]
        )
        if "tr064_wlan" not in sources:
            sources.append("tr064_wlan")

        if mac != primary_mac:
            alias_sources = target.setdefault("wlan_mac_aliases", [])
            if mac not in alias_sources:
                alias_sources.append(mac)


def merge_tr064_data(devices: list[dict], extra_devices: list[dict]) -> None:
    """Merge TR-064 host records into the main device list by MAC address."""
    by_mac = {str(device.get("mac", "")).upper(): device for device in devices}
    for extra in extra_devices:
        mac = str(extra.get("mac", "")).upper()
        if not mac:
            continue
        if mac in by_mac:
            for key, value in extra.items():
                if value is not None and value != "":
                    by_mac[mac][key] = value
            sources = by_mac[mac].get("sources", ["fritzbox_landevice"])
            if "tr064_hosts" not in sources:
                sources.append("tr064_hosts")
            by_mac[mac]["sources"] = sources
        else:
            extra["sources"] = ["tr064_hosts"]
            devices.append(extra)
            by_mac[mac] = extra
