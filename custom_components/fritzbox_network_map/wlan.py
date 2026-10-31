"""TR-064 WLAN device-list retrieval for FRITZ!Box Network Map."""

import logging
from urllib.parse import urljoin
from xml.etree import ElementTree

_LOGGER = logging.getLogger(__name__)

_ALEXA_MAC = "68:F6:3B:6B:48:0A"


async def async_get_wlan_devices(client, error_cls) -> list[dict]:
    """Read AVM's documented XML list of currently associated WLAN devices.

    WLANConfiguration instances 1..3 are tried because FRITZ!Box models
    expose different radio bands/guest WLANs on different instances.
    """
    hosts: dict[str, dict] = {}

    for instance in (1, 2, 3):
        control_url = (
            f"{client.host}:49000/upnp/control/wlanconfig{instance}"
        )
        service = f"urn:dslforum-org:service:WLANConfiguration:{instance}"

        soap = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<s:Body><u:X_AVM-DE_GetWLANDeviceListPath '
            f'xmlns:u="{service}"/>'
            '</s:Body></s:Envelope>'
        )

        try:
            response_xml = await client._async_tr064_request(
                control_url,
                service,
                "X_AVM-DE_GetWLANDeviceListPath",
                soap,
            )
            root = ElementTree.fromstring(response_xml)
            path = client._find_text_by_local_name(
                root, "NewX_AVM-DE_WLANDeviceListPath"
            )

            if not path:
                _LOGGER.warning(
                    "WLAN-DIAGNOSE: WLANConfiguration%d lieferte "
                    "keinen WLAN-Listenpfad.",
                    instance,
                )
                continue

            list_url = urljoin(
                f"{client.host}:49000/",
                path.lstrip("/"),
            )

            async with client.session.get(
                list_url, timeout=20
            ) as response:
                response.raise_for_status()
                list_xml = await response.text()

            list_root = ElementTree.fromstring(list_xml)
            instance_macs: list[str] = []
            instance_count = 0

            for item in list_root.iter():
                if client._local_name(item.tag) != "Item":
                    continue

                fields = {
                    client._local_name(child.tag): (
                        child.text or ""
                    ).strip()
                    for child in item
                }

                mac = fields.get(
                    "AssociatedDeviceMACAddress", ""
                ).upper()

                if not mac:
                    continue

                instance_count += 1
                instance_macs.append(mac)

                device = {
                    "mac": mac,
                    "source": "tr064_wlan",
                }

                speed = client._parse_int(
                    fields.get("X_AVM-DE_Speed")
                )
                signal = client._parse_int(
                    fields.get("X_AVM-DE_SignalStrength")
                )
                channel = client._parse_int(
                    fields.get("AssociatedDeviceChannel")
                )
                width = client._parse_int(
                    fields.get("X_AVM-DE_ChannelWidth")
                )
                guest = client._parse_bool(
                    fields.get("AssociatedDeviceGuest")
                )

                if speed is not None:
                    device["wifi_speed_mbps"] = speed
                if signal is not None:
                    device["wifi_signal_strength"] = signal
                if channel is not None and channel > 0:
                    device["wifi_channel"] = channel
                if width is not None:
                    device["wifi_channel_width"] = width
                if guest is not None:
                    device["wifi_guest"] = guest

                if len(device) > 2:
                    hosts[mac] = {
                        **hosts.get(mac, {}),
                        **device,
                    }

            _LOGGER.warning(
                "WLAN-DIAGNOSE: WLANConfiguration%d: "
                "%d Einträge, Alexa vorhanden=%s, "
                "MAC-Adressen=%s",
                instance,
                instance_count,
                _ALEXA_MAC in instance_macs,
                sorted(set(instance_macs)),
            )

        except Exception as err:
            # A model may not expose every instance; keep trying the others.
            _LOGGER.warning(
                "WLANConfiguration%d konnte nicht gelesen werden "
                "(%s): %s",
                instance,
                type(err).__name__,
                err,
            )

    _LOGGER.warning(
        "WLAN-DIAGNOSE: Gesamtzahl eindeutiger WLAN-Geräte=%d, "
        "Alexa vorhanden=%s",
        len(hosts),
        _ALEXA_MAC in hosts,
    )

    if not hosts:
        raise error_cls(
            "Keine WLAN-Geräte aus der TR-064-WLAN-Liste gelesen. "
            "Bitte TR-064-Berechtigung und FRITZ!OS-Unterstützung prüfen."
        )

    return list(hosts.values())
