"""
NEURON Resources — CPU/Memory/Disk Monitoring
Reports node capacity for intelligent task distribution.
"""

import os
import time
import asyncio
import logging
import platform
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("neuron.resources")


@dataclass
class ResourceSnapshot:
    """Point-in-time resource measurement."""
    timestamp: float = 0.0
    cpu_percent: float = 0.0
    cpu_count: int = 0
    memory_total: int = 0       # bytes
    memory_used: int = 0
    memory_percent: float = 0.0
    disk_total: int = 0
    disk_used: int = 0
    disk_percent: float = 0.0
    load_avg: tuple = (0.0, 0.0, 0.0)
    platform: str = ""
    hostname: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "cpu": {"percent": self.cpu_percent, "count": self.cpu_count},
            "memory": {"total_mb": self.memory_total // (1024*1024),
                       "used_mb": self.memory_used // (1024*1024),
                       "percent": self.memory_percent},
            "disk": {"total_gb": self.disk_total // (1024**3),
                     "used_gb": self.disk_used // (1024**3),
                     "percent": self.disk_percent},
            "load_avg": self.load_avg,
            "platform": self.platform, "hostname": self.hostname
        }

    @property
    def capacity_score(self) -> float:
        """0-100 score of available capacity. Higher = more available."""
        cpu_avail = 100 - self.cpu_percent
        mem_avail = 100 - self.memory_percent
        return (cpu_avail * 0.6 + mem_avail * 0.4)

    @property
    def is_overloaded(self) -> bool:
        return self.cpu_percent > 90 or self.memory_percent > 90


class ResourceMonitor:
    """Monitors system resources without external dependencies."""

    def __init__(self, report_interval: int = 5,
                 cpu_threshold: float = 85, memory_threshold: float = 90):
        self.report_interval = report_interval
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.history: list = []
        self.max_history = 360  # 30 min at 5s intervals
        self._running = False
        self._latest: Optional[ResourceSnapshot] = None

    def snapshot(self) -> ResourceSnapshot:
        """Take a point-in-time resource snapshot using OS tools."""
        snap = ResourceSnapshot(
            timestamp=time.time(),
            cpu_count=os.cpu_count() or 1,
            platform=platform.system(),
            hostname=platform.node()
        )

        # CPU via load average
        try:
            load = os.getloadavg()
            snap.load_avg = load
            snap.cpu_percent = min(100.0, (load[0] / snap.cpu_count) * 100)
        except:
            snap.cpu_percent = 0.0

        # Memory via vm_stat (macOS) or /proc/meminfo (Linux)
        if platform.system() == "Darwin":
            snap = self._mac_memory(snap)
        else:
            snap = self._linux_memory(snap)

        # Disk
        try:
            st = os.statvfs("/")
            snap.disk_total = st.f_blocks * st.f_frsize
            snap.disk_used = (st.f_blocks - st.f_bfree) * st.f_frsize
            snap.disk_percent = (snap.disk_used / snap.disk_total * 100) if snap.disk_total else 0
        except: pass

        self._latest = snap
        return snap

    def _mac_memory(self, snap: ResourceSnapshot) -> ResourceSnapshot:
        try:
            r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            snap.memory_total = int(r.stdout.strip())
            r2 = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
            lines = r2.stdout.split("\n")
            page_size = 16384  # Default macOS page size
            pages = {}
            for line in lines:
                if ":" in line:
                    parts = line.split(":")
                    key = parts[0].strip()
                    val = parts[1].strip().rstrip(".")
                    try: pages[key] = int(val)
                    except: pass
            active = pages.get("Pages active", 0) * page_size
            wired = pages.get("Pages wired down", 0) * page_size
            compressed = pages.get("Pages occupied by compressor", 0) * page_size
            snap.memory_used = active + wired + compressed
            snap.memory_percent = (snap.memory_used / snap.memory_total * 100) if snap.memory_total else 0
        except: pass
        return snap

    def _linux_memory(self, snap: ResourceSnapshot) -> ResourceSnapshot:
        try:
            with open("/proc/meminfo") as f:
                info = {}
                for line in f:
                    parts = line.split(":")
                    key = parts[0].strip()
                    val = int(parts[1].strip().split()[0]) * 1024  # kB to bytes
                    info[key] = val
            snap.memory_total = info.get("MemTotal", 0)
            snap.memory_used = snap.memory_total - info.get("MemAvailable", info.get("MemFree", 0))
            snap.memory_percent = (snap.memory_used / snap.memory_total * 100) if snap.memory_total else 0
        except: pass
        return snap

    async def start_monitoring(self):
        self._running = True
        logger.info(f"Resource monitoring started (interval: {self.report_interval}s)")
        while self._running:
            snap = self.snapshot()
            self.history.append(snap)
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]

            if snap.cpu_percent > self.cpu_threshold:
                logger.warning(f"CPU high: {snap.cpu_percent:.1f}%")
            if snap.memory_percent > self.memory_threshold:
                logger.warning(f"Memory high: {snap.memory_percent:.1f}%")

            await asyncio.sleep(self.report_interval)

    def stop(self):
        self._running = False

    @property
    def latest(self) -> Optional[ResourceSnapshot]:
        return self._latest or self.snapshot()

    def average(self, minutes: int = 5) -> dict:
        cutoff = time.time() - (minutes * 60)
        recent = [s for s in self.history if s.timestamp > cutoff]
        if not recent:
            return {"cpu": 0, "memory": 0, "samples": 0}
        return {
            "cpu": sum(s.cpu_percent for s in recent) / len(recent),
            "memory": sum(s.memory_percent for s in recent) / len(recent),
            "capacity_score": sum(s.capacity_score for s in recent) / len(recent),
            "samples": len(recent)
        }

    def status(self) -> dict:
        snap = self.latest
        return {
            "current": snap.to_dict(),
            "capacity_score": snap.capacity_score,
            "overloaded": snap.is_overloaded,
            "avg_5min": self.average(5),
            "history_size": len(self.history)
        }
