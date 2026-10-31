from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .fritzbox_client import FritzBoxClient
from .snmp_switch import async_get_mac_table, async_get_lldp_neighbors
from .network_model import merge_switch_observations

_LOGGER = logging.getLogger(__name__)


class FritzBoxNetworkMapCoordinator(DataUpdateCoordinator):
    """Coordinate periodic updates from the FRITZ!Box client."""

    def __init__(self, hass, client: FritzBoxClient, scan_interval: int, switches: list[dict] | None = None) -> None:
        self.client = client
        self.switches = switches or []
        self.last_switch_errors: dict[str, str] = {}
        self.last_switch_records: dict[str, list[dict]] = {}
        self.last_lldp_neighbors: dict[str, list[dict]] = {}
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_method=self._async_update_data,
            update_interval=timedelta(seconds=scan_interval or DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> list[dict]:
        """Fetch current devices while translating client errors for HA."""
        try:
            devices = await self.client.async_get_devices()
            self.last_switch_errors = {}
            switch_records = {}
            self.last_lldp_neighbors = {}
            for switch in self.switches:
                host = switch.get("host", "unknown")
                try:
                    records = await async_get_mac_table(switch)
                    for mac, record in records.items():
                        switch_records.setdefault(mac, []).append(record)
                except Exception as err:
                    self.last_switch_errors[host] = f"{type(err).__name__}: {err}"
                    _LOGGER.warning("SNMP-MAC-Abfrage von Switch %s fehlgeschlagen: %s", host, err)
                try:
                    self.last_lldp_neighbors[host] = await async_get_lldp_neighbors(switch)
                except Exception as err:
                    self.last_switch_errors[f"{host} (LLDP)"] = f"{type(err).__name__}: {err}"
                    self.last_lldp_neighbors[host] = []
                    _LOGGER.info("LLDP-Abfrage von Switch %s nicht verfügbar: %s", host, err)

            # Keep the complete latest SNMP MAC table for inspection in Home Assistant.
            self.last_switch_records = {mac: [dict(item) for item in items] for mac, items in switch_records.items()}

            # Merge switch inventory and all learned MACs into the existing model.
            model = getattr(self.client, "network_model", None) or {}
            self.client.network_model = merge_switch_observations(
                model, devices, self.switches, switch_records, self.last_switch_errors
            )
            self.client.network_model["lldp_neighbors"] = {
                host: [dict(item) for item in items]
                for host, items in self.last_lldp_neighbors.items()
            }
            self.client.mesh_model = self.client.network_model
            nas_mac = "90:09:D0:79:05:43"
            if nas_mac in switch_records:
                _LOGGER.info("SNMP-NAS-Abgleich: MAC %s wurde auf %s gelernt", nas_mac, switch_records[nas_mac])
            else:
                _LOGGER.info("SNMP-NAS-Abgleich: MAC %s nicht in Switch-MAC-Tabelle; gelernte MACs=%s", nas_mac, len(switch_records))
            return devices
        except Exception as err:
            raise UpdateFailed(
                f"FRITZ!Box-Daten konnten nicht abgerufen werden: {err}"
            ) from err
