"""
Halloween Countdown plugin for LEDMatrix.

A trick-or-treat street at sunset: a pumpkin-head kid and a little ghost
walk past brick, stone and wooden houses while leaves blow, fog drifts and
surprises happen (bats, a witch across the moon, trick-or-treat stops...).
The days to Halloween show in the top-left corner. On October 31 it shows
HAPPY HALLOWEEN; from November 1 it counts to next year's.

The drawing lives in halloween_scene.py. This file connects it to LEDMatrix:
it reads the settings, works out how many days are left, and hands a fresh
frame to the display many times a second.
"""

import time
from datetime import date, datetime
from typing import Any, Dict, Optional

from PIL import Image

from src.plugin_system.base_plugin import BasePlugin

from halloween_scene import draw_scene

DESIGN_WIDTH, DESIGN_HEIGHT = 128, 32   # the scene is drawn for two 64x32 panels
MAX_FRAME_GAP = 1.0   # seconds; a longer gap between frames means we were off screen


def _colour(value, default):
    """Turn a [r, g, b] setting into a colour, or use the default if it's bad."""
    try:
        r, g, b = (max(0, min(255, int(c))) for c in value)
        return (r, g, b)
    except (TypeError, ValueError):
        return default


class HalloweenCountdownPlugin(BasePlugin):
    """Animated Halloween countdown."""

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        # Ask the display loop to call display() many times a second instead
        # of once a second, so everything moves smoothly.
        self.needs_high_fps = True
        # The scene has its own clock, which only runs while the scene is on
        # screen. That way the walk, the window figures and the surprises
        # carry on where they left off each time the plugin comes round in
        # the rotation, instead of happening unseen while other plugins show.
        self._scene_time = 0.0
        self._last_tick = None
        self._last_frame = 0.0
        self._apply_config()

    def _apply_config(self) -> None:
        cfg = self.config
        self.show_countdown = bool(cfg.get("show_countdown", True))
        self.speed = max(0.25, min(3.0, float(cfg.get("animation_speed", 1.0))))
        self.scene_options = {
            "surprise_every": max(15, min(300, int(cfg.get("surprise_every_seconds", 30)))),
            "glow": cfg.get("sunset_glow", "full"),
            "fog": max(0, min(200, int(cfg.get("fog", 100)))) / 100,
            "leaves": max(0, min(20, int(cfg.get("leaves", 10)))),
            "text_colour": _colour(cfg.get("countdown_color"), (255, 120, 10)),
        }
        # Scene brightness, as a lookup table that scales every colour value.
        brightness = max(10, min(100, int(cfg.get("brightness", 100)))) / 100
        self._brightness_table = None if brightness >= 1 else [
            int(v * brightness) for v in range(256)] * 3
        fps = max(5, min(60, int(cfg.get("animation_fps", 30))))
        self._frame_interval = 1.0 / fps

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Settings saved in the web UI take effect straight away."""
        super().on_config_change(new_config)
        self._apply_config()

    def _get_global_timezone(self) -> Optional[str]:
        """The LEDMatrix timezone setting, or None when it cannot be read."""
        try:
            for source in (self.plugin_manager, self.cache_manager):
                config_manager = getattr(source, "config_manager", None)
                if config_manager:
                    return config_manager.get_timezone()
        except Exception as e:
            self.logger.warning(f"Error getting global timezone: {e}")
        return None

    def _today(self) -> date:
        """Today's date in the LEDMatrix timezone, falling back to system time."""
        tz_name = self._get_global_timezone()
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                return datetime.now(ZoneInfo(tz_name)).date()
            except Exception:
                pass
        return date.today()

    def days_until_halloween(self) -> int:
        """0 on Halloween; from November 1, counts to next year's."""
        today = self._today()
        halloween = date(today.year, 10, 31)
        if today > halloween:
            halloween = date(today.year + 1, 10, 31)
        return (halloween - today).days

    def update(self) -> None:
        # Nothing to download: the countdown is worked out from the date
        # every frame in display().
        pass

    def display(self, force_clear: bool = False) -> None:
        now = time.monotonic()
        # The display loop calls us up to ~100 times a second. About 30
        # frames a second looks just as smooth and leaves the Pi time to do
        # everything else.
        if not force_clear and now - self._last_frame < self._frame_interval:
            return
        self._last_frame = now

        if self._last_tick is not None:
            gap = now - self._last_tick
            # A long gap means we were off screen: don't count that time.
            if gap < MAX_FRAME_GAP:
                self._scene_time += gap * self.speed
        self._last_tick = now

        frame = draw_scene(self._scene_time, self.days_until_halloween(),
                           DESIGN_WIDTH, DESIGN_HEIGHT, self.scene_options,
                           show_text=self.show_countdown)
        self._show(frame)

    def _show(self, frame: Image.Image) -> None:
        """Put the 128x32 scene on the display, whatever its size."""
        width = self.display_manager.width
        height = self.display_manager.height
        if (width, height) != (DESIGN_WIDTH, DESIGN_HEIGHT):
            scale = min(width // DESIGN_WIDTH, height // DESIGN_HEIGHT)
            if scale >= 1:
                # A bigger display: blow the scene up by a whole number so
                # the pixels stay crisp, and centre it.
                frame = frame.resize((DESIGN_WIDTH * scale, DESIGN_HEIGHT * scale), Image.NEAREST)
            canvas = Image.new("RGB", (width, height), (0, 0, 0))
            # A smaller display shows the middle of the scene.
            canvas.paste(frame, ((width - frame.width) // 2, (height - frame.height) // 2))
            frame = canvas
        if self._brightness_table:
            frame = frame.point(self._brightness_table)
        self.display_manager.image.paste(frame, (0, 0))
        self.display_manager.update_display()
