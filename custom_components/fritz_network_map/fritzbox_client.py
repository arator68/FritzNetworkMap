from __future__ import annotations

import hashlib
from urllib.parse import quote
from xml.etree import ElementTree

from aiohttp import ClientError, ClientSession


class FritzBoxError(Exception):
    """Base error for FRITZ!Box communication."""


class FritzBoxAuthError(FritzBoxError):
    """Authentication failed."""


class FritzBoxClient:
    """Async client for FRITZ!Box device data."""

    def __init__(self, session: ClientSession, host: str, username: str, password: str):
        self.session = session
        self.host = host.rstrip("/")
        self.username = username
        self.password = password

    async def async_get_devices(self) -> list[dict]:
        sid = await self._async_get_sid()
        devices = await self._async_get_landevice(sid)
        # Optional enrichment: if TR-064 is unavailable, keep the primary list.
        try:
            extra_devices = await self._async_get_tr064_hosts(sid)
            self._merge_tr064_data(devices, extra_devices)
        except Exception:
            pass
        return devices

    async def _async_get_landevice(self, sid: str) -> list[dict]:
        url = f"{self.host}/api/v0/generic/landevice"
        headers = {"Authorization": f"AVM-SID {sid}"}
        async with self.session.get(url, headers=headers, timeout=20) as response:
            if response.status in (401, 403):
                raise FritzBoxAuthError("FRITZ!Box hat den Zugriff abgelehnt.")
            response.raise_for_status()
            payload = await response.json(content_type=None)

        raw_devices = payload.get("landevice")
        if not isinstance(raw_devices, list):
            raise FritzBoxError("Antwort enthält kein gültiges 'landevice'-Array.")

        devices = []
        for item in raw_devices:
            if not isinstance(item, dict) or not item.get("mac"):
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
                "mac": str(item["mac"]).upper(),
                "name": item.get("name"),
                "friendly_name": item.get("friendlyname"),
                "ip_addresses": ips,
                "connection_type": "unknown",
                "interface_type": None,
                "active": None,
                "source": "fritzbox_landevice",
            })
        return devices

    async def _async_get_tr064_hosts(self, sid: str) -> list[dict]:
        """Read host interface details from the FRITZ!Box TR-064 Hosts service."""
        endpoint = f"{self.host}/upnp/control/hosts?sid={quote(sid, safe='')}"
        service = "urn:dslforum-org:service:Hosts:1"

        async def soap_action(action: str, body: str) -> ElementTree.Element:
            headers = {
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPAction": f'"{service}#{action}"',
            }
            envelope = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
                + '<s:Body><u:' + action + ' xmlns:u="' + service + '">'
                + body + '</u:' + action + '></s:Body></s:Envelope>'
            )
            async with self.session.post(
                endpoint, data=envelope.encode("utf-8"), headers=headers, timeout=15
            ) as response:
                response.raise_for_status()
                xml = await response.text()
            return ElementTree.fromstring(xml)

        root = await soap_action("GetHostNumberOfEntries", "")
        count_text = next(
            (el.text for el in root.iter() if el.tag.endswith("NewHostNumberOfEntries")),
            None,
        )
        if not count_text:
            return []
        try:
            count = min(int(count_text), 512)
        except ValueError:
            return []

        result = []
        for index in range(count):
            try:
                root = await soap_action(
                    "GetGenericHostEntry", f"<NewIndex>{index}</NewIndex>"
                )
            except Exception:
                break
            values = {
                el.tag.rsplit("}", 1)[-1]: (el.text or "")
                for el in root.iter()
                if el.tag.rsplit("}", 1)[-1].startswith("New")
            }
            mac = values.get("NewMACAddress", "").strip().upper()
            if not mac:
                continue
            interface = values.get("NewInterfaceType", "").strip()
            active_text = values.get("NewActive", "").strip().lower()
            result.append({
                "mac": mac,
                "name": values.get("NewHostName") or values.get("NewHostNameByDHCP") or None,
                "ip": values.get("NewIPAddress") or None,
                "interface_type": interface or None,
                "connection_type": self._connection_type(interface),
                "active": active_text in ("1", "true"),
            })
        return result

    @staticmethod
    def _connection_type(interface_type: str) -> str:
        normalized = interface_type.strip().lower()
        if normalized in ("ethernet", "802.3", "lan"):
            return "LAN"
        if normalized in ("802.11", "wlan", "wifi", "wi-fi"):
            return "WLAN"
        return "unknown"

    @staticmethod
    def _merge_tr064_data(devices: list[dict], extra_devices: list[dict]) -> None:
        by_mac = {str(item.get("mac", "")).upper(): item for item in devices}
        for extra in extra_devices:
            mac = str(extra.get("mac", "")).upper()
            device = by_mac.get(mac)
            if device is None:
                device = {
                    "mac": mac,
                    "name": extra.get("name"),
                    "friendly_name": None,
                    "ip_addresses": [],
                    "connection_type": extra.get("connection_type", "unknown"),
                    "interface_type": extra.get("interface_type"),
                    "active": extra.get("active"),
                    "source": "tr064_hosts",
                }
                if extra.get("ip"):
                    device["ip_addresses"].append(
                        {"address": extra["ip"], "type": "IPv4"}
                    )
                devices.append(device)
                by_mac[mac] = device
                continue

            if extra.get("interface_type"):
                device["interface_type"] = extra["interface_type"]
                device["connection_type"] = extra.get("connection_type", "unknown")
            if extra.get("active") is not None:
                device["active"] = extra["active"]
            if not device.get("name") and extra.get("name"):
                device["name"] = extra["name"]
            ip = extra.get("ip")
            if ip and not any(
                item.get("address") == ip for item in device.get("ip_addresses", [])
            ):
                device.setdefault("ip_addresses", []).append(
                    {"address": ip, "type": "IPv4"}
                )

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
        hash1 = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt1, iterations1, dklen=32
        )
        hash2 = hashlib.pbkdf2_hmac("sha256", hash1, salt2, iterations2, dklen=32)
        return f"{salt2.hex()}${hash2.hex()}"
