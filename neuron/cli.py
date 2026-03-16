"""
NEURON CLI — Command Line Interface
Start nodes, join clusters, submit tasks, check status from the terminal.
"""

import argparse
import asyncio
import json
import logging
import sys
import os

from neuron.orchestrator import NeuronOrchestrator, NeuronConfig


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S"
    )


async def cmd_start(args):
    """Start a NEURON node."""
    config = NeuronConfig(
        name=args.name,
        host=args.host,
        port=args.port,
        role=args.role,
        max_peers=args.max_peers,
        max_tasks=args.max_tasks,
        balancer_strategy=args.strategy
    )

    if args.config:
        config = NeuronConfig.from_file(args.config)

    node = NeuronOrchestrator(config)

    # Register built-in compute functions
    @node.register_function("echo")
    def echo(*args, **kwargs):
        return {"echo": args, "kwargs": kwargs}

    @node.register_function("sum")
    def sum_numbers(numbers):
        return sum(numbers)

    @node.register_function("multiply")
    def multiply(a, b):
        return a * b

    @node.register_function("system_info")
    def system_info():
        snap = node.resources.snapshot()
        return snap.to_dict()

    await node.start()

    # Join seeds if provided
    if args.seed:
        for seed in args.seed:
            host, port = seed.rsplit(":", 1)
            await node.join_cluster(host, int(port))

    print(f"\nNEURON node '{config.name}' running on {config.host}:{config.port}")
    print(f"Role: {config.role} | Strategy: {config.balancer_strategy}")
    print(f"Functions: {node.registry.list_functions()}")
    print(f"\nPress Ctrl+C to stop\n")

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nShutting down...")
        await node.stop()


async def cmd_status(args):
    """Get cluster status."""
    from neuron.network import NetworkNode, Message
    net = NetworkNode("status-client", port=0)
    peer = await net.connect_to(args.host, args.port)
    if not peer:
        print(f"Cannot connect to {args.host}:{args.port}")
        return

    await net.send_to(peer.peer_id,
        Message("status_request", {}, "status-client"))

    # Wait for response
    msg = await asyncio.wait_for(peer.receive(), timeout=5)
    if msg:
        print(json.dumps(msg.payload, indent=2))
    else:
        print("No response")
    await net.stop()


async def cmd_submit(args):
    """Submit a task to the cluster."""
    from neuron.network import NetworkNode, Message
    net = NetworkNode("task-client", port=0)
    peer = await net.connect_to(args.host, args.port)
    if not peer:
        print(f"Cannot connect to {args.host}:{args.port}")
        return

    payload_data = {}
    if args.payload:
        payload_data = json.loads(args.payload)

    task_msg = Message("task_submit", {
        "name": args.task,
        "function": args.task,
        "args": payload_data.get("args", []),
        "kwargs": payload_data.get("kwargs", {}),
        "priority": args.priority
    }, "task-client")

    await net.send_to(peer.peer_id, task_msg)
    print(f"Task '{args.task}' submitted")

    # Wait for result
    try:
        msg = await asyncio.wait_for(peer.receive(), timeout=args.timeout)
        if msg:
            print(f"Result: {json.dumps(msg.payload, indent=2)}")
    except asyncio.TimeoutError:
        print("Waiting for result timed out")
    await net.stop()


def main():
    parser = argparse.ArgumentParser(
        prog="neuron",
        description="NEURON — Distributed Computing Platform"
    )
    sub = parser.add_subparsers(dest="command")

    # start
    p_start = sub.add_parser("start", help="Start a NEURON node")
    p_start.add_argument("--name", default=f"neuron-{os.getpid()}")
    p_start.add_argument("--host", default="0.0.0.0")
    p_start.add_argument("--port", type=int, default=8400)
    p_start.add_argument("--role", choices=["worker", "coordinator", "hybrid"], default="hybrid")
    p_start.add_argument("--seed", nargs="*", help="Seed nodes (host:port)")
    p_start.add_argument("--max-peers", type=int, default=50)
    p_start.add_argument("--max-tasks", type=int, default=10)
    p_start.add_argument("--strategy", choices=["weighted_capacity", "round_robin", "least_loaded"],
                         default="weighted_capacity")
    p_start.add_argument("--config", help="Path to config JSON file")
    p_start.add_argument("-v", "--verbose", action="store_true")

    # status
    p_status = sub.add_parser("status", help="Get node/cluster status")
    p_status.add_argument("--host", default="127.0.0.1")
    p_status.add_argument("--port", type=int, default=8400)

    # submit
    p_submit = sub.add_parser("submit", help="Submit a task")
    p_submit.add_argument("--task", required=True, help="Task/function name")
    p_submit.add_argument("--payload", help='JSON payload: {"args": [...], "kwargs": {...}}')
    p_submit.add_argument("--host", default="127.0.0.1")
    p_submit.add_argument("--port", type=int, default=8400)
    p_submit.add_argument("--priority", type=int, default=0)
    p_submit.add_argument("--timeout", type=int, default=30)

    # join
    p_join = sub.add_parser("join", help="Join a cluster")
    p_join.add_argument("--seed", required=True, help="Seed node (host:port)")
    p_join.add_argument("--port", type=int, default=8401)
    p_join.add_argument("--name", default=f"neuron-{os.getpid()}")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    setup_logging(getattr(args, "verbose", False))

    if args.command == "start":
        asyncio.run(cmd_start(args))
    elif args.command == "status":
        asyncio.run(cmd_status(args))
    elif args.command == "submit":
        asyncio.run(cmd_submit(args))
    elif args.command == "join":
        async def do_join():
            host, port = args.seed.rsplit(":", 1)
            config = NeuronConfig(name=args.name, port=args.port)
            node = NeuronOrchestrator(config)
            await node.start()
            await node.join_cluster(host, int(port))
            print(f"Joined cluster via {args.seed}")
            try:
                while True: await asyncio.sleep(1)
            except KeyboardInterrupt:
                await node.stop()
        asyncio.run(do_join())


if __name__ == "__main__":
    main()
