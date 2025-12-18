from pydantic import BaseModel
from typing import List, Optional, Dict, Any

# --- Basic Models ---

class CountStats(BaseModel):
    success: int
    failure: int

class ServiceStats(BaseModel):
    uptime: float
    success: int
    failure: int
    max: float
    avg: float
    min: float
    jitter: float

class ServiceCheckSchema(BaseModel):
    name: str
    url: Optional[str]
    status: str
    latency: Optional[float]
    stats: ServiceStats

class DistributionItem(BaseModel):
    value: int
    name: str

class MonitorStats(BaseModel):
    max: float
    avg: float
    min: float
    jitter: float

# --- Nested Response Structures ---

class SystemInfo(BaseModel):
    cpu: float
    ram: float
    disk: float
    containers: int
    uptime: str

class MonitorInfo(BaseModel):
    worker_status: Optional[int]
    uptime: Dict[str, float]
    distribution: List[DistributionItem]
    stats: MonitorStats

class NetworkInfo(BaseModel):
    internet_status: bool
    uptime: float
    uptime_counts: Optional[CountStats]
    stats: MonitorStats

class HistoryData(BaseModel):
    times: List[str]
    system: Dict[str, List[Optional[float]]]
    cycle_duration: List[Optional[int]]
    ping: List[Optional[float]]
    services: Dict[str, List[Optional[float]]]

# --- Main API Response ---

class DashboardResponse(BaseModel):
    last_updated: str
    system: SystemInfo
    monitor: MonitorInfo
    network: NetworkInfo
    services: List[ServiceCheckSchema]
    history: HistoryData
