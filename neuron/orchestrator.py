"""
NEURON Orchestrator — Ties All Modules Together
The main entry point that initializes and coordinates all subsystems.
"""

import asyncio
import json
import uuid
import time
import logging
import signal
import os
from typing import Optional

from neuron.network import NetworkNode, Message
from neuron.discovery import DiscoveryService
from neuron.tasks import TaskDistributor, TaskRegistry
from neuron.resources import ResourceMonitor
from neuron.security import SecurityManager
from neuron.balancer import LoadBalancer

logger = logging.getLogger("neuron")


class NeuronConfig:
    """Configuration for a NEURON node."""

    def __init__(self, **kwargs):
        self.name = kwargs.get("name", f"neuron-{uuid.uuid4().hex[:6]}")
        self.host = kwargs.get("host", "0.0.0.0")
        self.port = kwargs.get("port", 8400)
        self.role = kwargs.get("role", "hybrid")  # worker | coordinator | hybrid
        self.max_peers = kwargs.get("max_peers", 50)
        self.heartbeat_interval = kwargs.get("heartbeat_interval", 10)
        self.resource_interval = kwargs.get("resource_interval", 5)
        self.max_tasks = kwargs.get("max_tasks", 10)
        self.cluster_secret = kwargs.get("cluster_secret", "")
        self.seed_nodes = kwargs.get("seed_nodes", [])
        self.auth_enabled = kwargs.get("auth_enabled", True)
        self.balancer_strategy = kwargs.get("balancer_strategy", "weighted_capacity")

    @classmethod
    def from_file(cls, path: str) -> "NeuronConfig":
        with open(path) as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def from_env(cls) -> "NeuronConfig":
        return cls(
            name=os.environ.get("NEURON_NAME", f"neuron-{uuid.uuid4().hex[:6]}"),
            host=os.environ.get("NEURON_HOST", "0.0.0.0"),
            port=int(os.environ.get("NEURON_PORT", 8400)),
            role=os.environ.get("NEURON_ROLE", "hybrid"),
            max_peers=int(os.environ.get("NEURON_MAX_PEERS", 50)),
            cluster_secret=os.environ.get("NEURON_CLUSTER_SECRET", ""),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name, "host": self.host, "port": self.port,
            "role": self.role, "max_peers": self.max_peers,
            "max_tasks": self.max_tasks, "auth_enabled": self.auth_enabled,
            "balancer_strategy": self.balancer_strategy
        }


class NeuronOrchestrator:
    """
    Main NEURON node — orchestrates all subsystems.
    
    Usage:
        node = NeuronOrchestrator(NeuronConfig(name="worker-1", port=8400))
        await node.start()
        task = await node.submit_task("compute", "sum_numbers", [1, 2, 3])
        await node.stop()
    """

    def __init__(self, config: NeuronConfig = None):
        self.config = config or NeuronConfig()
        self.started_at: float = 0
        self._running = False

        # Initialize subsystems
        self.network = NetworkNode(self.config.name, self.config.host, self.config.port)
        self.discovery = DiscoveryService(
            self.network,
            heartbeat_interval=self.config.heartbeat_interval,
            max_peers=self.config.max_peers
        )
        self.registry = TaskRegistry()
        self.tasks = TaskDistributor(self.network, self.registry)
        self.resources = ResourceMonitor(report_interval=self.config.resource_interval)
        self.security = SecurityManager(self.config.name, self.config.cluster_secret)
        self.balancer = LoadBalancer(strategy=self.config.balancer_strategy)

        # Register self in balancer
        self.balancer.register_node(self.config.name, max_tasks=self.config.max_tasks)

        # Register internal message handlers
        self.network.register_handler("resource_report", self._handle_resource_report)
        self.network.register_handler("status_request", self._handle_status_request)

        # Add seed nodes
        for seed in self.config.seed_nodes:
            if ":" in seed:
                host, port = seed.rsplit(":", 1)
                self.discovery.add_seed(host, int(port))

    async def start(self):
        """Start the NEURON node and all subsystems."""
        self.started_at = time.time()
        self._running = True

        # Start network
        await self.network.start()

        # Start discovery
        await self.discovery.start()

        # Start resource monitoring
        asyncio.create_task(self.resources.start_monitoring())

        # Start resource broadcasting
        asyncio.create_task(self._broadcast_resources())

        logger.info(f"NEURON node '{self.config.name}' started on port {self.config.port}")
        logger.info(f"  Role: {self.config.role}")
        logger.info(f"  Max peers: {self.config.max_peers}")
        logger.info(f"  Max tasks: {self.config.max_tasks}")
        logger.info(f"  Strategy: {self.config.balancer_strategy}")

    async def stop(self):
        """Gracefully stop all subsystems."""
        self._running = False
        self.resources.stop()
        await self.discovery.stop()
        await self.network.stop()
        logger.info(f"NEURON node '{self.config.name}' stopped")

    async def submit_task(self, name: str, function: str,
                          args: list = None, kwargs: dict = None,
                          priority: int = 0) -> "Task":
        """Submit a task for distributed execution."""
        return await self.tasks.submit(name, function, args, kwargs, priority)

    def register_function(self, name: str = None):
        """Decorator to register a function for distributed execution."""
        return self.registry.register(name)

    async def join_cluster(self, host: str, port: int) -> bool:
        """Join an existing NEURON cluster."""
        peer = await self.network.connect_to(host, port)
        if peer:
            self.discovery.add_seed(host, port)
            logger.info(f"Joined cluster via {host}:{port}")
            return True
        return False

    async def _broadcast_resources(self):
        """Periodically broadcast resource status to peers."""
        while self._running:
            await asyncio.sleep(15)
            snap = self.resources.latest
            if snap:
                msg = Message("resource_report", {
                    "node_id": self.config.name,
                    "capacity_score": snap.capacity_score,
                    "cpu": snap.cpu_percent,
                    "memory": snap.memory_percent,
                    "load_avg": snap.load_avg
                }, self.config.name)
                await self.network.broadcast(msg)

                # Update own balancer entry
                self.balancer.update_capacity(self.config.name, snap)

    async def _handle_resource_report(self, msg: Message, peer):
        """Update load balancer with peer's resource report."""
        node_id = msg.payload.get("node_id", msg.sender)
        if node_id not in self.balancer.nodes:
            self.balancer.register_node(node_id)
        cap = self.balancer.nodes[node_id]
        cap.capacity_score = msg.payload.get("capacity_score", 50)
        cap.last_updated = time.time()

    async def _handle_status_request(self, msg: Message, peer):
        """Respond to status requests from peers."""
        status = self.status()
        await self.network.send_to(msg.sender,
            Message("status_response", status, self.config.name, reply_to=msg.id))

    @property
    def uptime(self) -> float:
        return time.time() - self.started_at if self.started_at else 0

    def status(self) -> dict:
        """Full system status."""
        return {
            "node": self.config.to_dict(),
            "uptime": round(self.uptime, 1),
            "running": self._running,
            "network": self.network.status(),
            "discovery": self.discovery.status(),
            "tasks": self.tasks.status(),
            "resources": self.resources.status(),
            "security": self.security.status(),
            "balancer": self.balancer.status()
        }
