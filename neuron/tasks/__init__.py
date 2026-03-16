"""
NEURON Tasks — Distributed Task Execution
Serializes, distributes, and aggregates computational tasks across nodes.
"""

import asyncio
import json
import uuid
import time
import logging
import traceback
from enum import Enum
from typing import Dict, Any, Callable, Optional, List
from dataclasses import dataclass, field
from neuron.network import NetworkNode, Message

logger = logging.getLogger("neuron.tasks")


class TaskState(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: str = ""
    name: str = ""
    function: str = ""
    args: list = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)
    state: TaskState = TaskState.PENDING
    result: Any = None
    error: str = ""
    assigned_to: str = ""
    submitted_by: str = ""
    priority: int = 0
    created_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    timeout: int = 300
    retries: int = 0
    max_retries: int = 3

    def __post_init__(self):
        if not self.id: self.id = str(uuid.uuid4())[:12]
        if not self.created_at: self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "function": self.function,
            "args": self.args, "kwargs": self.kwargs, "state": self.state.value,
            "result": self.result, "error": self.error,
            "assigned_to": self.assigned_to, "submitted_by": self.submitted_by,
            "priority": self.priority, "created_at": self.created_at,
            "started_at": self.started_at, "completed_at": self.completed_at,
            "timeout": self.timeout, "retries": self.retries
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        t = cls()
        for k, v in data.items():
            if k == "state": v = TaskState(v)
            if hasattr(t, k): setattr(t, k, v)
        return t

    @property
    def duration(self) -> float:
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        if self.started_at:
            return time.time() - self.started_at
        return 0


class TaskRegistry:
    """Registry of executable functions that can be distributed."""

    def __init__(self):
        self._functions: Dict[str, Callable] = {}

    def register(self, name: str = None):
        def decorator(func):
            fn_name = name or func.__name__
            self._functions[fn_name] = func
            return func
        return decorator

    def get(self, name: str) -> Optional[Callable]:
        return self._functions.get(name)

    def list_functions(self) -> List[str]:
        return list(self._functions.keys())


class TaskDistributor:
    """Distributes tasks across the NEURON network."""

    def __init__(self, network: NetworkNode, registry: TaskRegistry = None):
        self.network = network
        self.registry = registry or TaskRegistry()
        self.tasks: Dict[str, Task] = {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self._running = False

        # Register network handlers
        self.network.register_handler("task_submit", self._handle_task_submit)
        self.network.register_handler("task_result", self._handle_task_result)
        self.network.register_handler("task_status", self._handle_task_status)

    async def submit(self, name: str, function: str, args: list = None,
                     kwargs: dict = None, priority: int = 0, timeout: int = 300) -> Task:
        task = Task(
            name=name, function=function,
            args=args or [], kwargs=kwargs or {},
            priority=priority, timeout=timeout,
            submitted_by=self.network.node_id
        )
        self.tasks[task.id] = task

        # Try to execute locally first if we have the function
        local_fn = self.registry.get(function)
        if local_fn:
            task.state = TaskState.RUNNING
            task.started_at = time.time()
            task.assigned_to = self.network.node_id
            asyncio.create_task(self._execute_local(task, local_fn))
        else:
            # Distribute to network
            task.state = TaskState.QUEUED
            msg = Message("task_submit", task.to_dict(), self.network.node_id)
            await self.network.broadcast(msg)

        logger.info(f"Task {task.id} submitted: {task.name} ({task.state.value})")
        return task

    async def _execute_local(self, task: Task, func: Callable):
        try:
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(
                    func(*task.args, **task.kwargs), timeout=task.timeout)
            else:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, lambda: func(*task.args, **task.kwargs)),
                    timeout=task.timeout)

            task.result = result
            task.state = TaskState.COMPLETED
            task.completed_at = time.time()
            logger.info(f"Task {task.id} completed in {task.duration:.2f}s")
        except asyncio.TimeoutError:
            task.state = TaskState.FAILED
            task.error = f"Timeout after {task.timeout}s"
            task.completed_at = time.time()
        except Exception as e:
            task.error = f"{type(e).__name__}: {e}"
            task.retries += 1
            if task.retries < task.max_retries:
                task.state = TaskState.QUEUED
                logger.warning(f"Task {task.id} failed, retry {task.retries}/{task.max_retries}")
                asyncio.create_task(self._execute_local(task, func))
            else:
                task.state = TaskState.FAILED
                task.completed_at = time.time()
                logger.error(f"Task {task.id} failed permanently: {e}")

    async def _handle_task_submit(self, msg: Message, peer):
        task = Task.from_dict(msg.payload)
        func = self.registry.get(task.function)
        if func:
            task.assigned_to = self.network.node_id
            task.state = TaskState.RUNNING
            task.started_at = time.time()
            self.tasks[task.id] = task
            await self._execute_local(task, func)
            # Send result back
            result_msg = Message("task_result", task.to_dict(), self.network.node_id, reply_to=msg.id)
            await self.network.send_to(msg.sender, result_msg)

    async def _handle_task_result(self, msg: Message, peer):
        task_data = msg.payload
        task_id = task_data.get("id")
        if task_id in self.tasks:
            self.tasks[task_id] = Task.from_dict(task_data)
            logger.info(f"Received result for task {task_id} from {msg.sender}")

    async def _handle_task_status(self, msg: Message, peer):
        task_id = msg.payload.get("task_id")
        task = self.tasks.get(task_id)
        if task:
            await self.network.send_to(msg.sender,
                Message("task_result", task.to_dict(), self.network.node_id, reply_to=msg.id))

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def status(self) -> dict:
        states = {}
        for task in self.tasks.values():
            states[task.state.value] = states.get(task.state.value, 0) + 1
        return {
            "total_tasks": len(self.tasks),
            "by_state": states,
            "registered_functions": self.registry.list_functions()
        }
