from sqlalchemy import Column, Integer, Float, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class MonitoringCycle(Base):
    __tablename__ = "monitoring_cycles"

    id = Column(String, primary_key=True)
    timestamp_lima = Column(String, nullable=False, index=True)
    cpu_percent = Column(Float, nullable=False)
    ram_percent = Column(Float, nullable=False)
    ram_used_mb = Column(Float, nullable=False)
    disk_percent = Column(Float, nullable=False)
    uptime_seconds = Column(Float)
    container_count = Column(Integer, nullable=False)
    internet_status = Column(Boolean, nullable=False)
    ping_ms = Column(Float)
    worker_status = Column(Integer)
    cycle_duration_ms = Column(Integer)

    # Relationship to service checks
    service_checks = relationship("ServiceCheck", back_populates="cycle", cascade="all, delete-orphan")

class ServiceCheck(Base):
    __tablename__ = "service_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id = Column(String, ForeignKey("monitoring_cycles.id"), nullable=False, index=True)
    service_name = Column(String, nullable=False, index=True)
    service_url = Column(String)
    status = Column(String, nullable=False)
    status_code = Column(Integer)
    latency_ms = Column(Float)
    error_message = Column(String)

    # Back-relationship to the cycle
    cycle = relationship("MonitoringCycle", back_populates="service_checks")
