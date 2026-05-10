from pydantic import BaseModel


class BatteryParams(BaseModel):
    asset_id: str
    capacity_mwh: float = 100.0
    max_charge_mw: float = 25.0
    max_discharge_mw: float = 25.0
    eta_charge: float = 0.92
    eta_discharge: float = 0.92
    soc_min_pct: float = 0.10
    soc_max_pct: float = 0.90
    initial_soc_pct: float = 0.50
    degradation_per_mwh: float = 2.0

    @property
    def soc_min_mwh(self) -> float:
        return self.soc_min_pct * self.capacity_mwh

    @property
    def soc_max_mwh(self) -> float:
        return self.soc_max_pct * self.capacity_mwh

    @property
    def initial_soc_mwh(self) -> float:
        return self.initial_soc_pct * self.capacity_mwh
