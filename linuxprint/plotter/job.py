"""Plain data describing a plotter job -- no device I/O, no GPL code.

Kept deliberately dumb (plain dataclasses that serialize straight to the
JSON job schema documented in vendor/plot_cli.py) so the decision logic
here stays trivial to unit test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# A handful of common Cameo cutting-mat presets. Keys match exactly what the
# vendored Graphtec.py's CAMEO_MATS dict expects for its "cuttingmat" setup
# parameter; "no_mat" (matless / roll-fed cutting) has no size limit of its
# own and just uses media_width_mm/media_height_mm directly.
MEDIA_PRESETS: dict[str, tuple[str | None, float, float]] = {
    "A4": (None, 210.0, 297.0),
    "Letter": (None, 215.9, 279.4),
    "cameo_12x12": ("cameo_12x12", 304.8, 304.8),
    "cameo_12x24": ("cameo_12x24", 304.8, 609.6),
    "portrait_8x12": ("portrait_8x12", 203.2, 304.8),
    "portrait_8_5x12": ("portrait_8_5x12", 215.9, 304.8),
}

DEFAULT_MEDIA_PRESET = "A4"


@dataclass
class RegmarkSettings:
    enabled: bool = False
    search: bool = True
    width_mm: float = 180.0
    length_mm: float = 230.0
    origin_x_mm: float = 15.0
    origin_y_mm: float = 20.0
    quad: bool = False

    def to_json(self) -> dict | None:
        if not self.enabled:
            return None
        return {
            "search": self.search,
            "width_mm": self.width_mm,
            "length_mm": self.length_mm,
            "origin_x_mm": self.origin_x_mm,
            "origin_y_mm": self.origin_y_mm,
            "quad": self.quad,
        }


@dataclass
class ToolPass:
    tool: str  # "blade" | "pen"
    paths: list[list[tuple[float, float]]]
    toolholder: int = 1
    speed: int = 10
    pressure: int = 27
    depth: int | None = None

    def to_json(self) -> dict:
        if self.tool not in ("blade", "pen"):
            raise ValueError(f"unknown tool {self.tool!r}, expected 'blade' or 'pen'")
        return {
            "tool": self.tool,
            "toolholder": self.toolholder,
            "speed": self.speed,
            "pressure": self.pressure,
            "depth": self.depth,
            "paths": [[list(point) for point in path] for path in self.paths],
        }


@dataclass
class PlotJob:
    passes: list[ToolPass] = field(default_factory=list)
    media_preset: str = DEFAULT_MEDIA_PRESET
    media_width_mm: float | None = None
    media_height_mm: float | None = None
    force_hardware: str | None = None
    dry_run: bool = False
    regmark: RegmarkSettings = field(default_factory=RegmarkSettings)

    def resolved_media(self) -> tuple[str | None, float, float]:
        """Returns (cuttingmat_key, width_mm, height_mm), applying any
        explicit width/height override on top of the chosen preset."""
        cuttingmat, width_mm, height_mm = MEDIA_PRESETS.get(
            self.media_preset, MEDIA_PRESETS[DEFAULT_MEDIA_PRESET]
        )
        if self.media_width_mm is not None:
            width_mm = self.media_width_mm
        if self.media_height_mm is not None:
            height_mm = self.media_height_mm
        return cuttingmat, width_mm, height_mm

    def to_json(self) -> dict:
        cuttingmat, width_mm, height_mm = self.resolved_media()
        return {
            "force_hardware": self.force_hardware,
            "dry_run": self.dry_run,
            "cuttingmat": cuttingmat,
            "media_width_mm": width_mm,
            "media_height_mm": height_mm,
            "regmark": self.regmark.to_json(),
            "passes": [p.to_json() for p in self.passes],
        }
