"""Expose the turntable stream in Home Assistant's media browser."""

from __future__ import annotations

from homeassistant.components.media_player import BrowseError, MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.const import CONF_NAME, CONF_URL
from homeassistant.core import HomeAssistant

from .const import CONF_MIME_TYPE, DEFAULT_MIME_TYPE, DEFAULT_NAME, DOMAIN, MEDIA_IDENTIFIER


async def async_get_media_source(hass: HomeAssistant) -> MediaSource:
    """Set up the turntable media source."""
    return TurntableMediaSource(hass)


class TurntableMediaSource(MediaSource):
    """Provide the turntable stream as a browsable media source."""

    name = DEFAULT_NAME

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the media source."""
        super().__init__(DOMAIN)
        self.hass = hass

    @property
    def _config(self) -> dict:
        return self.hass.data.get(DOMAIN, {})

    @property
    def _title(self) -> str:
        return self._config.get(CONF_NAME, DEFAULT_NAME)

    @property
    def _mime_type(self) -> str:
        return self._config.get(CONF_MIME_TYPE, DEFAULT_MIME_TYPE)

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve the stream to a playable URL."""
        if item.identifier != MEDIA_IDENTIFIER:
            raise Unresolvable(f"Unknown turntable media item: {item.identifier}")

        stream_url = self._config.get(CONF_URL)
        if not stream_url:
            raise Unresolvable("Turntable stream URL is not configured")

        return PlayMedia(stream_url, self._mime_type)

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Browse the turntable media source."""
        if item.identifier not in (None, ""):
            raise BrowseError(f"Unknown turntable media item: {item.identifier}")

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.APP,
            media_content_type=MediaType.MUSIC,
            title=self._title,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.MUSIC,
            children=[
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=MEDIA_IDENTIFIER,
                    media_class=MediaClass.MUSIC,
                    media_content_type=self._mime_type,
                    title=self._title,
                    can_play=True,
                    can_expand=False,
                )
            ],
        )
