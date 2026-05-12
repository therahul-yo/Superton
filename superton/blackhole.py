"""SuperTon black hole — animated boot mark.

Renders a tilted accretion-disk black hole in the terminal. The disk rotates
clockwise; the violet underglow breathes; the dark core stays still.

Frames are generated procedurally from oval geometry so the look can be tuned
by changing a few constants instead of hand-drawing 24 ASCII frames.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Iterator

from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live
from rich.text import Text

# Visual identity — warm disk, violet underglow, void core.
DISK_COLORS = ["#FFD93D", "#FFB347", "#FF6B35", "#E94E1B"]
UNDERGLOW = "#A23BFF"
CORE = "#0A0A0F"
SPECULAR = "#3A3A4F"

WIDTH = 52
HEIGHT = 16
CENTER_X = WIDTH / 2
CENTER_Y = HEIGHT / 2

# Disk oval — wider than tall (tilt forward).
DISK_RX = 22.0
DISK_RY = 4.5
DISK_THICKNESS = 1.4

# Sphere — circle in screen space.
SPHERE_R = 4.2
SPHERE_R2 = SPHERE_R * SPHERE_R


@dataclass
class Particle:
    """A point traveling along the disk's oval."""

    phase: float  # 0..1 around the oval
    intensity: float  # 0..1 brightness


def _disk_particles(count: int = 64) -> list[Particle]:
    return [
        Particle(phase=i / count, intensity=0.5 + 0.5 * math.sin(i * 0.7))
        for i in range(count)
    ]


def _in_sphere(x: float, y: float) -> bool:
    dx = x - CENTER_X
    dy = (y - CENTER_Y) * 2.2  # terminal cells are ~2x taller than wide
    return dx * dx + dy * dy <= SPHERE_R2


def _disk_position(phase: float) -> tuple[float, float, bool]:
    """Return (x, y, in_front) for a particle at oval phase."""
    angle = phase * 2 * math.pi
    x = CENTER_X + DISK_RX * math.cos(angle)
    y = CENTER_Y + DISK_RY * math.sin(angle)
    in_front = math.sin(angle) > 0
    return x, y, in_front


def _pick_disk_char(intensity: float) -> str:
    if intensity > 0.85:
        return "█"
    if intensity > 0.65:
        return "▓"
    if intensity > 0.4:
        return "▒"
    if intensity > 0.2:
        return "░"
    return "·"


def _pick_disk_color(intensity: float) -> str:
    idx = min(len(DISK_COLORS) - 1, int((1 - intensity) * len(DISK_COLORS)))
    return DISK_COLORS[idx]


def render_frame(t: float, *, speed: float = 1.0, pulse: float = 1.0) -> Text:
    """Render one frame at time t (seconds). Returns rich Text."""
    grid: list[list[tuple[str, str]]] = [[(" ", "default")] * WIDTH for _ in range(HEIGHT)]

    # Pass 1 — disk particles BEHIND the sphere.
    particles = _disk_particles(72)
    rotation = (t * 0.4 * speed) % 1.0

    for p in particles:
        phase = (p.phase + rotation) % 1.0
        x, y, in_front = _disk_position(phase)
        if in_front:
            continue
        ix, iy = int(round(x)), int(round(y))
        if 0 <= ix < WIDTH and 0 <= iy < HEIGHT:
            char = _pick_disk_char(p.intensity * pulse)
            color = _pick_disk_color(p.intensity * pulse)
            grid[iy][ix] = (char, color)

    # Pass 2 — sphere body (the void). Overwrites anything underneath.
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if _in_sphere(x, y):
                # tiny specular highlight at upper-left
                dx, dy = x - CENTER_X, y - CENTER_Y
                if dx < -1.5 and dy < -0.5 and (dx * dx + dy * dy * 4) < (SPHERE_R * 0.7) ** 2:
                    grid[y][x] = ("·", SPECULAR)
                else:
                    grid[y][x] = (" ", CORE)

    # Pass 3 — disk particles IN FRONT of the sphere.
    for p in particles:
        phase = (p.phase + rotation) % 1.0
        x, y, in_front = _disk_position(phase)
        if not in_front:
            continue
        ix, iy = int(round(x)), int(round(y))
        if 0 <= ix < WIDTH and 0 <= iy < HEIGHT:
            char = _pick_disk_char(p.intensity * pulse)
            color = _pick_disk_color(p.intensity * pulse)
            grid[iy][ix] = (char, color)

    # Pass 4 — violet underglow on rows just below the sphere.
    glow_strength = 0.5 + 0.5 * math.sin(t * 1.6)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if grid[y][x][0] != " ":
                continue
            dx = x - CENTER_X
            dy = y - CENTER_Y
            if dy > 0 and dy < SPHERE_R + 2 and abs(dx) < SPHERE_R + 1:
                if glow_strength > 0.7:
                    grid[y][x] = ("·", UNDERGLOW)

    out = Text()
    for row in grid:
        for char, color in row:
            if color == "default" or color == CORE:
                out.append(char)
            else:
                out.append(char, style=color)
        out.append("\n")
    return out


class BlackHole:
    """A renderable, animated black hole. Use as a context manager.

    Example:
        with BlackHole(console) as bh:
            do_work()
            bh.set_state("retrieving")
    """

    def __init__(self, console: Console, fps: int = 15):
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

    def __enter__(self) -> "BlackHole":
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
    fps = 18
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
