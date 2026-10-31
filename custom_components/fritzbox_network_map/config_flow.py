import voluptuous as vol
import ipaddress
from homeassistant import config_entries
from homeassistant.config_entries import OptionsFlow
from homeassistant.core import callback
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .fritzbox_client import FritzBoxAuthError, FritzBoxClient
from .snmp_switch import async_test_snmpv3


class NetworkTopologyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        # Current Home Assistant versions attach the ConfigEntry to the
        # OptionsFlow instance; the flow constructor takes no arguments.
        return NetworkTopologyOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip().rstrip("/")
            if "://" not in host:
                host = "http://" + host
            await self.async_set_unique_id(host.lower())
            self._abort_if_unique_id_configured()

            client = FritzBoxClient(
                session=async_get_clientsession(self.hass),
                host=host,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
            )
            try:
                await client.async_get_devices()
            except FritzBoxAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"FRITZ!Box ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        schema = vol.Schema({
            vol.Required(CONF_HOST, default="fritz.box"): str,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class NetworkTopologyOptionsFlow(OptionsFlow):
    """Manage switches after the FRITZ!Box integration is installed."""

    # Home Assistant exposes the active ConfigEntry through the base
    # OptionsFlow property. Do not assign to self.config_entry here: on
    # current Home Assistant versions that property is read-only.

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["scan_interval", "add_switch", "remove_switch", "done"],
        )

    async def async_step_scan_interval(self, user_input=None):
        """Configure the polling interval for FRITZ!Box and switch data."""
        if user_input is not None:
            options = dict(self.config_entry.options)
            options["scan_interval"] = int(user_input["scan_interval"])
            return self.async_create_entry(title="", data=options)

        current_interval = int(
            self.config_entry.options.get("scan_interval", 60)
        )
        schema = vol.Schema({
            vol.Required("scan_interval", default=current_interval): vol.All(
                int, vol.Range(min=10, max=3600)
            ),
        })
        return self.async_show_form(
            step_id="scan_interval",
            data_schema=schema,
            description_placeholders={
                "minimum": "10",
                "maximum": "3600",
            },
        )

    async def async_step_done(self, user_input=None):
        return self.async_create_entry(title="", data=dict(self.config_entry.options))

    def _switch_candidates(self):
        """Return FRITZ!Box devices classified as switches by the override database."""
        runtime = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
        coordinator = runtime.get("coordinator")
        client = runtime.get("client")
        devices = coordinator.data if coordinator and isinstance(coordinator.data, list) else []
        override_db = getattr(client, "device_overrides", None)
        candidates = {}
        for device in devices:
            if not isinstance(device, dict):
                continue
            mac = str(device.get("mac") or "").strip().replace("-", ":").upper()
            if not mac:
                continue
            override = override_db.lookup(device) if override_db else {}
            dtype = str(override.get("override_device_type") or device.get("device_type") or "").casefold()
            role = str(override.get("override_device_role") or device.get("device_role") or "").casefold()
            # Switch discovery uses the effective classification only.
            # Explicit device_overrides.csv values take precedence; never infer
            # a switch from a hostname, model string or vendor-specific pattern.
            is_switch = "switch" in dtype or "switch" in role
            if not is_switch:
                continue
            host = _device_ipv4(device)
            if not host:
                continue
            name = str(device.get("friendly_name") or device.get("name") or device.get("hostname") or override.get("override_model") or host).strip()
            model = str(override.get("override_model") or device.get("model") or "").strip()
            label = f"{name} — {host}" + (f" ({model})" if model else "")
            candidates[mac] = {"mac": mac, "host": host, "name": name, "model": model, "label": label}
        return candidates

    async def async_step_add_switch(self, user_input=None):
        """Select an already discovered switch, then configure its SNMPv3 access."""
        candidates = self._switch_candidates()
        if not candidates:
            return self.async_abort(reason="no_switch_candidates")
        if user_input is not None:
            selected_mac = user_input["device_mac"]
            selected = candidates.get(selected_mac)
            if selected is None:
                return self.async_abort(reason="switch_not_found")
            self._selected_switch = selected
            return await self.async_step_switch_credentials()

        schema = vol.Schema({
            vol.Required("device_mac"): vol.In({mac: item["label"] for mac, item in candidates.items()}),
        })
        return self.async_show_form(step_id="add_switch", data_schema=schema)

    async def async_step_switch_credentials(self, user_input=None):
        """Collect credentials for the switch selected from the override-backed list."""
        errors = {}
        selected = getattr(self, "_selected_switch", None)
        if not selected:
            return await self.async_step_add_switch()
        if user_input is not None:
            host = selected["host"]
            switch = {
                "id": host.lower(),
                "name": user_input["name"].strip() or selected["name"],
                "host": host,
                "port": int(user_input.get("port", 161)),
                "username": user_input["username"].strip(),
                "auth_protocol": user_input["auth_protocol"],
                "auth_password": user_input["auth_password"],
                "priv_protocol": user_input["priv_protocol"],
                "priv_password": user_input["priv_password"],
                "device_mac": selected["mac"],
            }
            switches = list(self.config_entry.options.get("switches", []))
            if any(item.get("host", "").lower() == host.lower() for item in switches):
                errors["base"] = "switch_already_configured"
            else:
                try:
                    await async_test_snmpv3(switch)
                except Exception as err:
                    _LOGGER.warning("SNMPv3-Test für Switch %s fehlgeschlagen: %s", host, err)
                    errors["base"] = "cannot_connect"
                else:
                    switches.append(switch)
                    return self.async_create_entry(title="", data={**self.config_entry.options, "switches": switches})

        schema = vol.Schema({
            vol.Required("name", default=selected["name"]): str,
            vol.Required("host", default=selected["host"]): str,
            vol.Optional("port", default=161): vol.All(int, vol.Range(min=1, max=65535)),
            vol.Required("username"): str,
            vol.Required("auth_protocol", default="SHA"): vol.In(["SHA", "SHA256", "MD5"]),
            vol.Required("auth_password"): str,
            vol.Required("priv_protocol", default="AES"): vol.In(["AES", "DES"]),
            vol.Required("priv_password"): str,
        })
        return self.async_show_form(step_id="switch_credentials", data_schema=schema, errors=errors, description_placeholders={"selected_switch": selected["label"]})

    async def async_step_remove_switch(self, user_input=None):
        switches = list(self.config_entry.options.get("switches", []))
        if not switches:
            return self.async_abort(reason="no_switches")
        if user_input is not None:
            remove_id = user_input["switch"]
            switches = [item for item in switches if item.get("id") != remove_id]
            return self.async_create_entry(title="", data={**self.config_entry.options, "switches": switches})
        options = {item["id"]: f"{item.get('name', item.get('host'))} ({item.get('host')})" for item in switches}
        schema = vol.Schema({vol.Required("switch"): vol.In(options)})
        return self.async_show_form(step_id="remove_switch", data_schema=schema)


def _device_ipv4(device: dict) -> str | None:
    """Extract a valid IPv4 address from a normalized FRITZ!Box device record."""
    for address in device.get("ip_addresses", []) or []:
        if not isinstance(address, dict):
            continue
        value = str(address.get("address") or "").strip()
        kind = str(address.get("type") or "").lower()
        if value and (kind in ("ipv4", "4") or "." in value):
            try:
                parsed = ipaddress.ip_address(value)
            except ValueError:
                continue
            if parsed.version == 4:
                return value
    for key in ("ipv4", "ip", "address"):
        value = str(device.get(key) or "").strip()
        try:
            parsed = ipaddress.ip_address(value)
        except ValueError:
            continue
        if parsed.version == 4:
            return value
    return None


_LOGGER = __import__("logging").getLogger(__name__)

