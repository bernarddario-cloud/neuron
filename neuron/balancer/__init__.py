"""
NEURON Load Balancer — Capacity-Aware Task Routing
Routes tasks to the most available node based on resource capacity.
"""

import time
import logging
from typing import Dict, List, Optional
from neuron.resources import ResourceSnapshot

logger = logging.getLogger("neuron.balancer")


class NodeCapacity:
    """Tracks a node's capacity for load balancing decisions."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.capacity_score: float = 100.0
        self.active_tasks: int = 0
        self.max_tasks: int = 10
        self.last_updated: float = time.time()
        self.total_completed: int = 0
        self.avg_task_duration: float = 0.0
        self.failures: int = 0
        self.weight: float = 1.0  # Manual weight override

    @property
    def available_slots(self) -> int:
        return max(0, self.max_tasks - self.active_tasks)

    @property
    def effective_score(self) -> float:
        """Combined score factoring capacity, slots, and reliability."""
        if self.available_slots == 0:
            return 0.0
        slot_ratio = self.available_slots / self.max_tasks
        reliability = max(0.1, 1.0 - (self.failures * 0.1))
        return self.capacity_score * slot_ratio * reliability * self.weight

    @property
    def is_available(self) -> bool:
        return self.available_slots > 0 and self.capacity_score > 10

    def update_from_snapshot(self, snapshot: ResourceSnapshot):
        self.capacity_score = snapshot.capacity_score
        self.last_updated = time.time()

    def task_assigned(self):
        self.active_tasks += 1

    def task_completed(self, duration: float):
        self.active_tasks = max(0, self.active_tasks - 1)
        self.total_completed += 1
        # Running average of task duration
        if self.avg_task_duration == 0:
            self.avg_task_duration = duration
        else:
            self.avg_task_duration = (self.avg_task_duration * 0.8) + (duration * 0.2)

    def task_failed(self):
        self.active_tasks = max(0, self.active_tasks - 1)
        self.failures += 1


class LoadBalancer:
    """Routes tasks to optimal nodes based on capacity and performance."""

    def __init__(self, strategy: str = "weighted_capacity"):
        self.nodes: Dict[str, NodeCapacity] = {}
        self.strategy = strategy  # weighted_capacity, round_robin, least_loaded
        self._rr_index = 0

    def register_node(self, node_id: str, max_tasks: int = 10, weight: float = 1.0):
        cap = NodeCapacity(node_id)
        cap.max_tasks = max_tasks
        cap.weight = weight
        self.nodes[node_id] = cap
        logger.info(f"Registered node {node_id} (max_tasks={max_tasks}, weight={weight})")

    def remove_node(self, node_id: str):
        self.nodes.pop(node_id, None)

    def update_capacity(self, node_id: str, snapshot: ResourceSnapshot):
        if node_id in self.nodes:
            self.nodes[node_id].update_from_snapshot(snapshot)

    def select_node(self, exclude: List[str] = None) -> Optional[str]:
        """Select the best node for a new task."""
        exclude = exclude or []
        available = {nid: cap for nid, cap in self.nodes.items()
                     if cap.is_available and nid not in exclude}

        if not available:
            return None

        if self.strategy == "weighted_capacity":
            return self._weighted_capacity(available)
        elif self.strategy == "round_robin":
            return self._round_robin(available)
        elif self.strategy == "least_loaded":
            return self._least_loaded(available)
        else:
            return self._weighted_capacity(available)

    def _weighted_capacity(self, nodes: Dict[str, NodeCapacity]) -> str:
        return max(nodes.keys(), key=lambda nid: nodes[nid].effective_score)

    def _round_robin(self, nodes: Dict[str, NodeCapacity]) -> str:
        ids = sorted(nodes.keys())
        self._rr_index = (self._rr_index + 1) % len(ids)
        return ids[self._rr_index]

    def _least_loaded(self, nodes: Dict[str, NodeCapacity]) -> str:
        return min(nodes.keys(), key=lambda nid: nodes[nid].active_tasks)

    def notify_assigned(self, node_id: str):
        if node_id in self.nodes:
            self.nodes[node_id].task_assigned()

    def notify_completed(self, node_id: str, duration: float):
        if node_id in self.nodes:
            self.nodes[node_id].task_completed(duration)

    def notify_failed(self, node_id: str):
        if node_id in self.nodes:
            self.nodes[node_id].task_failed()

    def status(self) -> dict:
        return {
            "strategy": self.strategy,
            "total_nodes": len(self.nodes),
            "available_nodes": sum(1 for n in self.nodes.values() if n.is_available),
            "total_capacity": sum(n.available_slots for n in self.nodes.values()),
            "nodes": {
                nid: {
                    "score": round(n.effective_score, 1),
                    "active": n.active_tasks,
                    "slots": n.available_slots,
                    "completed": n.total_completed,
                    "failures": n.failures
                }
                for nid, n in self.nodes.items()
            }
        }
