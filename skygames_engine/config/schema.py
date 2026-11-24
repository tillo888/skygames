"""Typed schema for config/rules.yaml.

Pydantic validates the file on load, so a typo (``top_ft: 11OOO``) or a
missing key fails immediately with a clear message instead of silently
changing scores. ``extra="forbid"`` also catches misspelled key names.
"""
from __future__ import annotations

from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AltitudeReference(_Strict):
    mode: Literal["MSL", "AGL"] = "MSL"
    ground_elevation_m: Optional[float] = None
    auto_ground_last_s: float = Field(10, gt=0)


class DataQuality(_Strict):
    max_h_acc_m: Optional[float] = 20
    max_v_acc_m: Optional[float] = 30
    min_num_sv: Optional[int] = 5
    max_accel_ms2: Optional[float] = 80
    min_sample_rate_hz: float = Field(1.0, gt=0)
    max_gap_in_window_s: float = Field(2.0, gt=0)
    min_peak_alt_ft: float = 11000


class Smoothing(_Strict):
    exit_window_s: float = Field(0.5, gt=0)
    opening_window_s: float = Field(0.6, gt=0)


class ExitDetection(_Strict):
    freefall_threshold_kph: float = Field(100, gt=0)
    sustain_s: float = Field(0.6, ge=0)
    lookback_s: float = Field(6.0, gt=0)
    near_zero_kph: float = Field(5, ge=0)
    near_zero_min_s: float = Field(0.3, ge=0)
    ramp_window_s: float = Field(0.5, gt=0)
    ramp_min_ms2: float = 8.0


class OpeningDetection(_Strict):
    min_alt_ft: float = 1500
    max_alt_ft: float = 4500
    threshold_kph: float = Field(100, gt=0)
    sustain_s: float = Field(1.5, ge=0)
    sustain_tolerance: float = Field(1.05, ge=1.0)
    prior_fast_lookback_s: float = Field(3.0, gt=0)

    @model_validator(mode="after")
    def _band(self):
        if self.min_alt_ft >= self.max_alt_ft:
            raise ValueError("The lowest opening altitude must be below the highest.")
        return self


class Detection(_Strict):
    exit: ExitDetection = ExitDetection()
    opening: OpeningDetection = OpeningDetection()


class Window(_Strict):
    top_ft: float = 11000
    bottom_ft: float = 5000

    @model_validator(mode="after")
    def _order(self):
        if self.bottom_ft >= self.top_ft:
            raise ValueError("Window bottom must be lower than window top.")
        return self


class TaskBase(_Strict):
    label: str
    unit: str
    rank: Literal["asc", "desc"]


class MaxHorizontalSpeedTask(TaskBase):
    label: str = "Max Horizontal Speed"
    unit: str = "kph"
    rank: Literal["asc", "desc"] = "desc"
    averaging_s: float = Field(0, ge=0)


class DistanceTask(TaskBase):
    label: str = "Max Straight-Line Distance"
    unit: str = "m"
    rank: Literal["asc", "desc"] = "desc"


class SpeedCourseTask(TaskBase):
    label: str = "1 km Speed Course"
    unit: str = "s"
    rank: Literal["asc", "desc"] = "asc"
    target_distance_m: float = Field(1000, gt=0)
    measure: Literal["ab_projection", "radial_from_start"] = "ab_projection"
    must_finish_in_window: bool = True


class Tasks(_Strict):
    max_horizontal_speed: MaxHorizontalSpeedTask = MaxHorizontalSpeedTask()
    distance: DistanceTask = DistanceTask()
    speed_course: SpeedCourseTask = SpeedCourseTask()


class Wind(_Strict):
    enabled: bool = False
    provider: Literal["open_meteo", "manual"] = "open_meteo"
    cache_path: str = "data/wind_cache.sqlite"
    cache_grid_deg: float = Field(0.25, gt=0)
    pressure_levels_hpa: List[int] = [1000, 975, 950, 925, 900, 850, 800, 700, 600, 500]
    timeout_s: float = Field(10, gt=0)


class Visualization(_Strict):
    png_dpi: int = Field(160, gt=10)
    profile_glide_ylim: Tuple[float, float] = (0, 2)
    kml_line_width: int = Field(4, gt=0)


class Rules(_Strict):
    rules_version: str
    altitude_reference: AltitudeReference = AltitudeReference()
    data_quality: DataQuality = DataQuality()
    smoothing: Smoothing = Smoothing()
    detection: Detection = Detection()
    window: Window = Window()
    tasks: Tasks = Tasks()
    wind: Wind = Wind()
    visualization: Visualization = Visualization()
