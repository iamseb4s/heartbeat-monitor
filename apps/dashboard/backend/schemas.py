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
    distribution: Optional[Dict[str, int]] = None # Detailed breakdown of status counts
    max: float
    avg: float
    min: float
    jitter: float

class ServiceCheckSchema(BaseModel):
    name: str
    service_type: str
    status: str
    status_code: Optional[int] = None
    latency: Optional[float]
    error: Optional[str] = None # Detailed error message (e.g., "Timeout", "HTTP 500")
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
    containers: str
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