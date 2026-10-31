"""Frontend resource registration for FRITZ!Box Network Map."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
CARD_URL_BASE = "/fritz_network_map/fritz-network-map-card.js"


async def async_register_card(hass: HomeAssistant, version: str) -> None:
    """Serve the bundled card and register it as a Lovelace resource."""
    card_path = Path(__file__).parent.parent / "www" / "fritz-network-map-card.js"
    versioned_url = f"{CARD_URL_BASE}?v={version}"

    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_BASE, str(card_path), cache_headers=True)]
        )
    except (AttributeError, TypeError):
        try:
            hass.http.register_static_path(CARD_URL_BASE, str(card_path), cache_headers=True)
        except (AttributeError, RuntimeError) as err:
            _LOGGER.error("Karten-Datei konnte nicht bereitgestellt werden: %s", err)
            return
    except RuntimeError as err:
        if "already" not in str(err).lower() and "registered" not in str(err).lower():
            _LOGGER.warning("Statischer Kartenpfad: %s", err)

    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None) if lovelace is not None else None
    if resources is None:
        _LOGGER.warning("Lovelace-Ressourcenspeicher nicht verfügbar. Karten-URL: %s", versioned_url)
        return

    if not hasattr(resources, "async_create_item"):
        _LOGGER.warning(
            "Lovelace-Ressourcen werden im YAML-Modus verwaltet. "
            "Bitte einmalig als JavaScript-Modul eintragen: %s", versioned_url
        )
        return

    try:
        if hasattr(resources, "async_load") and not getattr(resources, "loaded", True):
            await resources.async_load()
        existing = next(
            (item for item in resources.async_items()
             if item.get("url", "").split("?")[0] == CARD_URL_BASE),
            None,
        )
        if existing:
            if existing.get("url") != versioned_url or existing.get("res_type") != "module":
                await resources.async_update_item(
                    existing["id"], {"res_type": "module", "url": versioned_url}
                )
                _LOGGER.info("Lovelace-Kartenressource auf Version %s aktualisiert.", version)
        else:
            await resources.async_create_item({"res_type": "module", "url": versioned_url})
            _LOGGER.info("Lovelace-Kartenressource automatisch registriert: %s", versioned_url)
    except Exception as err:
        _LOGGER.exception("Automatische Registrierung der Lovelace-Karte fehlgeschlagen: %s", err)
