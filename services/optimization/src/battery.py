from pydantic import BaseModel, Field, model_validator
from typing import Self


class BatteryParams(BaseModel):
    asset_id: str
    capacity_mwh: float = Field(default=100.0, gt=0)
    max_charge_mw: float = Field(default=25.0, gt=0)
    max_discharge_mw: float = Field(default=25.0, gt=0)
    eta_charge: float = Field(default=0.92, gt=0, le=1.0)
    eta_discharge: float = Field(default=0.92, gt=0, le=1.0)
    soc_min_pct: float = Field(default=0.10, ge=0, le=1.0)
    soc_max_pct: float = Field(default=0.90, ge=0, le=1.0)
    initial_soc_pct: float = Field(default=0.50, ge=0, le=1.0)
    # Terminal SoC target: the optimizer must leave the battery at or above
    # this level at the end of each horizon.  Defaults to the midpoint of
    # the SoC window so that multi-day sims don't drain the battery on day 1
    # and stay pinned at soc_min for the rest.  Set to None to disable.
    terminal_soc_pct: float | None = Field(default=None, ge=0, le=1.0)
    degradation_per_mwh: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def _validate_soc_bounds(self) -> Self:
        if self.soc_min_pct >= self.soc_max_pct:
            raise ValueError(
                f"soc_min_pct ({self.soc_min_pct}) must be less than "
                f"soc_max_pct ({self.soc_max_pct})"
            )
        if not (self.soc_min_pct <= self.initial_soc_pct <= self.soc_max_pct):
            raise ValueError(
                f"initial_soc_pct ({self.initial_soc_pct}) must be within "
                f"[soc_min_pct ({self.soc_min_pct}), soc_max_pct ({self.soc_max_pct})]"
            )
        if self.terminal_soc_pct is not None:
            if not (self.soc_min_pct <= self.terminal_soc_pct <= self.soc_max_pct):
                raise ValueError(
                    f"terminal_soc_pct ({self.terminal_soc_pct}) must be within "
                    f"[soc_min_pct ({self.soc_min_pct}), soc_max_pct ({self.soc_max_pct})]"
                )
        return self

    @property
    def soc_min_mwh(self) -> float:
        return self.soc_min_pct * self.capacity_mwh

    @property
    def soc_max_mwh(self) -> float:
        return self.soc_max_pct * self.capacity_mwh

    @property
    def initial_soc_mwh(self) -> float:
        return self.initial_soc_pct * self.capacity_mwh

    @property
    def terminal_soc_mwh(self) -> float | None:
        """Target SoC at the end of the optimization horizon.
        Defaults to soc_min (floor) so the optimizer can use the full battery
        each day without being forced to refill. Set terminal_soc_pct explicitly
        to require a higher ending state."""
        if self.terminal_soc_pct is not None:
            return self.terminal_soc_pct * self.capacity_mwh
        # Default: floor — let the optimizer decide whether to refill
        return self.soc_min_pct * self.capacity_mwh
