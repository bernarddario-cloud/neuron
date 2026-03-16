"""
NEURON Discovery — Peer Finding + Health Checks
Automatic peer discovery via seed nodes, heartbeats, and peer exchange.
"""

import asyncio
import time
import logging
from typing import List, Set, Dict, Optional
from neuron.network import NetworkNode, Message

logger = logging.getLogger("neuron.discovery")


class PeerInfo:
    """Information about a known peer."""

    def __init__(self, node_id: str, host: str, port: int):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.last_seen = time.time()
        self.failures = 0
        self.is_connected = False
        self.capabilities = {}

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def is_alive(self) -> bool:
        return time.time() - self.last_seen < 120 and self.failures < 3


class DiscoveryService:
    """Handles peer discovery, heartbeats, and cluster membership."""

    def __init__(self, network: NetworkNode, heartbeat_interval: int = 10,
                 max_peers: int = 50):
        self.network = network
        self.heartbeat_interval = heartbeat_interval
        self.max_peers = max_peers
        self.known_peers: Dict[str, PeerInfo] = {}
        self.seed_nodes: List[tuple] = []
        self._running = False

        # Register handlers
        self.network.register_handler("heartbeat", self._handle_heartbeat)
        self.network.register_handler("peer_exchange", self._handle_peer_exchange)
        self.network.register_handler("peer_request", self._handle_peer_request)

    def add_seed(self, host: str, port: int):
        self.seed_nodes.append((host, port))

    async def start(self):
        self._running = True
        # Connect to seed nodes
        for host, port in self.seed_nodes:
            await self._try_connect(host, port)
        # Start background tasks
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._cleanup_loop())
        logger.info(f"Discovery started — {len(self.seed_nodes)} seeds, {len(self.known_peers)} known peers")

    async def stop(self):
        self._running = False

    async def _try_connect(self, host: str, port: int) -> bool:
        if self.network.peer_count >= self.max_peers:
            return False
        peer = await self.network.connect_to(host, port)
        if peer:
            self.known_peers[peer.peer_id] = PeerInfo(peer.peer_id, host, port)
            self.known_peers[peer.peer_id].is_connected = True
            # Request their peer list
            await self.network.send_to(peer.peer_id,
                Message("peer_request", {"requesting": self.network.node_id}, self.network.node_id))
            return True
        return False

    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            msg = Message("heartbeat", {
                "node_id": self.network.node_id,
                "port": self.network.port,
                "peers": self.network.peer_count,
                "uptime": time.time()
            }, self.network.node_id)
            await self.network.broadcast(msg)

    async def _cleanup_loop(self):
        while self._running:
            await asyncio.sleep(30)
            dead = [pid for pid, info in self.known_peers.items() if not info.is_alive]
            for pid in dead:
                self.known_peers.pop(pid, None)
                if pid in self.network.peers:
                    await self.network.peers[pid].close()
                    self.network.peers.pop(pid, None)
                    logger.info(f"Removed dead peer: {pid}")

            # Try to reconnect to known but disconnected peers
            for pid, info in self.known_peers.items():
                if not info.is_connected and info.is_alive and self.network.peer_count < self.max_peers:
                    await self._try_connect(info.host, info.port)

    async def _handle_heartbeat(self, msg: Message, peer):
        peer_id = msg.payload.get("node_id", msg.sender)
        if peer_id in self.known_peers:
            self.known_peers[peer_id].last_seen = time.time()
            self.known_peers[peer_id].failures = 0

    async def _handle_peer_exchange(self, msg: Message, peer):
        """Receive peer list from another node."""
        peers = msg.payload.get("peers", [])
        for p in peers:
            pid = p.get("node_id")
            if pid and pid != self.network.node_id and pid not in self.known_peers:
                info = PeerInfo(pid, p["host"], p["port"])
                self.known_peers[pid] = info
                logger.info(f"Discovered peer via exchange: {pid}")

    async def _handle_peer_request(self, msg: Message, peer):
        """Send our peer list to the requester."""
        peers = [{"node_id": p.node_id, "host": p.host, "port": p.port}
                 for p in self.known_peers.values() if p.is_alive]
        await self.network.send_to(msg.sender,
            Message("peer_exchange", {"peers": peers}, self.network.node_id, reply_to=msg.id))

    def status(self) -> dict:
        return {
            "known_peers": len(self.known_peers),
            "connected_peers": sum(1 for p in self.known_peers.values() if p.is_connected),
            "seeds": len(self.seed_nodes),
            "max_peers": self.max_peers,
            "alive_peers": sum(1 for p in self.known_peers.values() if p.is_alive)
        }
