"""Turntable media source integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import CONF_NAME, CONF_URL
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_MIME_TYPE,
    DEFAULT_MIME_TYPE,
    DEFAULT_NAME,
    DOMAIN,
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
                vol.Required(CONF_URL): cv.url,
                vol.Optional(CONF_MIME_TYPE, default=DEFAULT_MIME_TYPE): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the turntable media source from YAML."""
    hass.data[DOMAIN] = config[DOMAIN]
    return True
