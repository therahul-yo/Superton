"""SuperTon black hole — animated boot mark.

Renders a tilted accretion-disk black hole in the terminal. The disk rotates
clockwise; the violet underglow breathes; the dark core stays still.

Frames are generated procedurally from oval geometry so the look can be tuned
by changing a few constants instead of hand-drawing 24 ASCII frames.
"""

from __future__ import annotations

import math
import time

from rich.console import Console
from rich.live import Live
from rich.text import Text

# Visual identity — warm disk, violet underglow, void core.
DISK_COLORS = ["#FFF7B8", "#FFD166", "#FF8A2A", "#F0471F"]
UNDERGLOW = "#B024F2"
CORE = "#0A0A0F"
SPECULAR = "#5B2B73"

WIDTH = 62
HEIGHT = 22
CENTER_X = WIDTH / 2
CENTER_Y = HEIGHT / 2

DISK_RX = 25.5
DISK_RY = 4.7
HORIZON_R = 5.8
SAMPLES = ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75))
GLYPHS = "  ·░▒▓█"


def _pick_disk_color(intensity: float) -> str:
    idx = min(len(DISK_COLORS) - 1, int((1 - intensity) * len(DISK_COLORS)))
    return DISK_COLORS[idx]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _glyph(value: float) -> str:
    return GLYPHS[int(_clamp(value) * (len(GLYPHS) - 1))]


def _cell_sample(px: float, py: float, t: float, speed: float, pulse: float) -> tuple[float, str, int]:
    """Return numeric brightness, color, and layer for one sub-cell sample."""
    dx = px - CENTER_X
    dy = py - CENTER_Y
    rot = t * speed
    angle = math.atan2(dy / DISK_RY, dx / DISK_RX)
    ellipse = (dx / DISK_RX) ** 2 + (dy / DISK_RY) ** 2

    # Back accretion ring.
    ring = 1.0 - abs(ellipse - 1.0) / 0.18
    if ring > 0:
        swirl = 0.55 + 0.45 * math.sin(angle * 7.0 - rot * math.tau * 2.2)
        doppler = 0.65 + 0.35 * math.cos(angle + math.pi * 0.88)
        brightness = _clamp(ring * (0.45 + 0.5 * swirl) * doppler * pulse)
        color = _pick_disk_color(brightness)
        layer = 1
    else:
        brightness = 0.0
        color = "default"
        layer = 0

    # Bright front lens, thinner than a full terminal row.
    front = 1.0 - (abs(dy - 1.25) / 0.62 + (abs(dx) / (DISK_RX + 1.5)) ** 2.4)
    if front > 0:
        front_wave = 0.82 + 0.18 * math.sin(dx * 0.45 - rot * math.tau * 3.5)
        front_brightness = _clamp(front * front_wave * 1.25)
        if front_brightness > brightness or layer < 3:
            brightness = front_brightness
            color = "#FFF4A8" if front_brightness > 0.62 else "#FFB02E"
            layer = 3

    # Event horizon. Terminal cells are tall, so scale y for a round shape.
    horizon = (dx / HORIZON_R) ** 2 + ((dy + 0.95) / (HORIZON_R * 0.58)) ** 2
    if horizon <= 1.0 and py < CENTER_Y + 1.3:
        rim = _clamp((1.0 - horizon) * 1.6)
        left_glow = _clamp((-dx - 1.0) / HORIZON_R) * 0.55
        brightness = max(0.18, left_glow * rim)
        color = SPECULAR if left_glow > 0.12 else "#000000"
        layer = 4

    # Underglow appears below the disk and breathes over time.
    glow = 1.0 - ((dx / 8.2) ** 2 + ((dy - 5.0) / 3.2) ** 2)
    glow *= 0.55 + 0.45 * math.sin(t * 1.8)
    if glow > 0.08 and layer < 2:
        brightness = max(brightness, _clamp(glow * 0.82))
        color = UNDERGLOW
        layer = 2

    return brightness, color, layer


def render_frame(t: float, *, speed: float = 1.0, pulse: float = 1.0) -> Text:
    """Render one frame at time t (seconds). Returns rich Text."""
    out = Text()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            total = 0.0
            colors: dict[str, float] = {}
            for sx, sy in SAMPLES:
                brightness, color, _layer = _cell_sample(x + sx, y + sy, t, speed, pulse)
                total += brightness
                colors[color] = colors.get(color, 0.0) + brightness
            value = total / len(SAMPLES)
            color = max(colors, key=colors.get) if colors else "default"
            if color == "#000000" and value > 0:
                value = max(value, 0.7)
            char = _glyph(value)
            if color == "default" or char == " ":
                out.append(char)
            else:
                out.append(char, style=color)
        out.append("\n")
    return out


def mascot_frame(t: float = 0.0) -> Text:
    """Small terminal-native fallback mark for non-shell contexts."""
    out = Text()
    segments = [
        [("        ▄▄████▄▄        ", "#FFB02E")],
        [("     ▄██", "#FFF4A8"), ("▀      ▀", "#FFB02E"), ("██▄     ", "#FF8A2A")],
        [("   ▄█▀ ", "#FFF4A8"), ("  ▄▄▄▄  ", "#07050A"), (" ▀█▄   ", "#F0471F")],
        [("▄▄█▀", "#FFD166"), ("              ", "#07050A"), ("▀█▄▄", "#FF8A2A")],
        [("████", "#FF8A2A"), ("████████████", "#FFF4A8"), ("████", "#FFD166")],
        [(" ▀██▄", "#C56A1B"), ("  ▀██████▀  ", "#8A3F10"), ("▄██▀ ", "#F0471F")],
        [("    ▀██▄", "#5B2B73"), ("      ", "#09050D"), ("▄██▀    ", "#7837E8")],
        [("       ▀", "#5B2B73"), ("▓▓▓▓▓▓", "#B024F2"), ("▀       ", "#E0378A")],
    ]
    for line in segments:
        for text, style in line:
            out.append(text, style=style)
        out.append("\n")
    return out


class BlackHole:
    """A renderable, animated black hole. Use as a context manager.

    Example:
        with BlackHole(console) as bh:
            do_work()
            bh.set_state("retrieving")
    """

    def __init__(self, console: Console, fps: int = 24):
        self.console = console
        self.fps = fps
        self._start = time.time()
        self._state = "idle"
        self._live: Live | None = None

    def _frame(self) -> Text:
        t = time.time() - self._start
        speed = {"idle": 1.0, "ingesting": 2.0, "retrieving": 1.5, "generating": 0.8}.get(
            self._state, 1.0
        )
        pulse = 1.0
        return render_frame(t, speed=speed, pulse=pulse)

    def set_state(self, state: str) -> None:
        self._state = state

    def __enter__(self) -> BlackHole:
        self._live = Live(
            self._frame(),
            console=self.console,
            refresh_per_second=self.fps,
            transient=True,
        )
        self._live.__enter__()
        return self

    def tick(self) -> None:
        if self._live:
            self._live.update(self._frame())

    def __exit__(self, *exc) -> None:
        if self._live:
            self._live.__exit__(*exc)


def play_boot(console: Console, duration: float = 1.6) -> None:
    """Play the boot animation for `duration` seconds, then exit."""
    fps = 24
    end = time.time() + duration
    with Live(console=console, refresh_per_second=fps, transient=False) as live:
        while time.time() < end:
            t = time.time()
            live.update(render_frame(t))
            time.sleep(1 / fps)
        live.update(render_frame(time.time()))


def static_frame() -> Text:
    """Single frame for static contexts (CI, --no-animation)."""
    return render_frame(0.0)
