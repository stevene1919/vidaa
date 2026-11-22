"""Media browser support for VIDAA Smart TV media player."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaType,
)

from ..const import CONF_ENABLE_CEC_NAMES, DEFAULT_ENABLE_CEC_NAMES
from ..tv.media import build_media_player_source_list

if TYPE_CHECKING:
    from . import VidaaMediaPlayer

_LOGGER = logging.getLogger(__name__)

__all__ = ["MediaPlayerBrowseMixin"]


class MediaPlayerBrowseMixin:
    """Browse media mixin for VidaaMediaPlayer."""

    async def async_browse_media(
        self: VidaaMediaPlayer,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse applications, TV input sources, and channels."""
        if media_content_type in (None, "root") and media_content_id in (None, "root"):
            return self._build_root_browser()

        if media_content_type in ("apps", MediaType.APP) or media_content_id == "apps":
            return self._build_apps_browser()

        if media_content_type in ("inputs", "sources") or media_content_id == "inputs":
            return self._build_inputs_browser()

        if media_content_type in ("channels", MediaType.CHANNEL) or media_content_id == "channels":
            return self._build_channels_browser()

        return self._build_root_browser()

    def _build_root_browser(self: VidaaMediaPlayer) -> BrowseMedia:
        """Construct the root container browsing tree."""
        children: list[BrowseMedia] = []

        if self._app_dict:
            children.append(
                BrowseMedia(
                    title="Applications",
                    media_class=MediaClass.DIRECTORY,
                    media_content_id="apps",
                    media_content_type="apps",
                    can_play=False,
                    can_expand=True,
                )
            )

        if self._source_dict:
            children.append(
                BrowseMedia(
                    title="Inputs & Sources",
                    media_class=MediaClass.DIRECTORY,
                    media_content_id="inputs",
                    media_content_type="inputs",
                    can_play=False,
                    can_expand=True,
                )
            )

        if getattr(self, "_channel_infos", None):
            children.append(
                BrowseMedia(
                    title="Live Channels",
                    media_class=MediaClass.DIRECTORY,
                    media_content_id="channels",
                    media_content_type="channels",
                    can_play=False,
                    can_expand=True,
                )
            )

        return BrowseMedia(
            title=self._name or "VIDAA Smart TV",
            media_class=MediaClass.DIRECTORY,
            media_content_id="root",
            media_content_type="root",
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.DIRECTORY,
        )

    def _build_apps_browser(self: VidaaMediaPlayer) -> BrowseMedia:
        """Build items list of installed applications."""
        items: list[BrowseMedia] = []
        for app_name, app_info in self._app_dict.items():
            thumb = None
            if isinstance(app_info, dict):
                icon = app_info.get("httpIcon")
                if icon and "http" in icon:
                    thumb = "http" + icon.split("http", 1)[1]

            items.append(
                BrowseMedia(
                    title=str(app_name),
                    media_class=MediaClass.APP,
                    media_content_id=str(app_name),
                    media_content_type=MediaType.APP,
                    can_play=True,
                    can_expand=False,
                    thumbnail=thumb,
                )
            )

        return BrowseMedia(
            title="Applications",
            media_class=MediaClass.DIRECTORY,
            media_content_id="apps",
            media_content_type="apps",
            can_play=False,
            can_expand=True,
            children=items,
            children_media_class=MediaClass.APP,
        )

    def _build_inputs_browser(self: VidaaMediaPlayer) -> BrowseMedia:
        """Build items list of physical/CEC input sources (excluding standalone apps)."""
        enable_cec = self._options.get(CONF_ENABLE_CEC_NAMES, DEFAULT_ENABLE_CEC_NAMES)
        inputs_only = build_media_player_source_list(
            source_dict=self._source_dict,
            app_dict=self._app_dict,
            current_source=self._source,
            connected_device=self._resolve_connected_device(),
            enable_cec=enable_cec,
            include_apps=False,
        )

        items: list[BrowseMedia] = [
            BrowseMedia(
                title=s_name,
                media_class=MediaClass.CHANNEL,
                media_content_id=s_name,
                media_content_type="source",
                can_play=True,
                can_expand=False,
            )
            for s_name in inputs_only
        ]

        return BrowseMedia(
            title="Inputs & Sources",
            media_class=MediaClass.DIRECTORY,
            media_content_id="inputs",
            media_content_type="inputs",
            can_play=False,
            can_expand=True,
            children=items,
            children_media_class=MediaClass.CHANNEL,
        )

    def _build_channels_browser(self: VidaaMediaPlayer) -> BrowseMedia:
        """Build items list of TV tuner channels."""
        items: list[BrowseMedia] = []
        channels = getattr(self, "_channel_infos", {}) or {}
        for ch_id, ch_info in channels.items():
            name = ch_info.get("name") if isinstance(ch_info, dict) else str(ch_info)
            num = ch_info.get("number") if isinstance(ch_info, dict) else ch_id
            title = f"{name} ({num})" if name and num else (name or str(num))
            items.append(
                BrowseMedia(
                    title=title,
                    media_class=MediaClass.CHANNEL,
                    media_content_id=str(num or ch_id),
                    media_content_type=MediaType.CHANNEL,
                    can_play=True,
                    can_expand=False,
                )
            )

        return BrowseMedia(
            title="Live Channels",
            media_class=MediaClass.DIRECTORY,
            media_content_id="channels",
            media_content_type="channels",
            can_play=False,
            can_expand=True,
            children=items,
            children_media_class=MediaClass.CHANNEL,
        )
