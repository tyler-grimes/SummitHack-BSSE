from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ── ERCOT ─────────────────────────────────────────────────────────────────────

class ErcotMeta(BaseModel):
    total_records: int = Field(alias="totalRecords")
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")
    current_page: int = Field(alias="currentPage")


class ErcotSppRecord(BaseModel):
    """Settlement Point Price (RTM LMP) from NP6-905-CD."""
    delivery_date: str = Field(alias="deliveryDate")
    delivery_hour: int = Field(alias="deliveryHour")
    delivery_interval: int = Field(alias="deliveryInterval")
    settlement_point: str = Field(alias="settlementPoint")
    settlement_point_type: str = Field(alias="settlementPointType")
    settlement_point_price: float = Field(alias="settlementPointPrice")
    dst_flag: str | None = Field(default=None, alias="DSTFlag")


class ErcotSppResponse(BaseModel):
    meta: ErcotMeta = Field(alias="_meta")
    data: list[ErcotSppRecord]


class ErcotDamRecord(BaseModel):
    """Day-Ahead Settlement Point Price from NP4-190-CD."""
    delivery_date: str = Field(alias="deliveryDate")
    delivery_hour: int = Field(alias="deliveryHour")
    settlement_point: str = Field(alias="settlementPoint")
    settlement_point_type: str = Field(alias="settlementPointType")
    settlement_point_price: float = Field(alias="settlementPointPrice")


class ErcotDamResponse(BaseModel):
    meta: ErcotMeta = Field(alias="_meta")
    data: list[ErcotDamRecord]


# ── PJM ───────────────────────────────────────────────────────────────────────

class PjmRtLmpRecord(BaseModel):
    """Real-time hourly LMP from rt_hrl_lmps."""
    datetime_beginning_utc: datetime
    pnode_id: int
    pnode_name: str
    voltage: str | None = None
    equipment: str | None = None
    type: str | None = None
    zone: str | None = None
    total_lmp_rt: float
    system_energy_price_rt: float
    congestion_price_rt: float
    marginal_loss_price_rt: float


class PjmDaLmpRecord(BaseModel):
    """Day-ahead hourly LMP from da_hrl_lmps."""
    datetime_beginning_utc: datetime
    pnode_id: int
    pnode_name: str
    type: str | None = None
    zone: str | None = None
    total_lmp_da: float
    system_energy_price_da: float
    congestion_price_da: float
    marginal_loss_price_da: float


class PjmAncillaryRecord(BaseModel):
    """Ancillary service price from ancillary_services."""
    datetime_beginning_utc: datetime
    ancillary_service: str
    unit: str
    value: float


class PjmPaginatedResponse(BaseModel):
    items: list[dict[str, Any]]
    total_rows: int | None = None
