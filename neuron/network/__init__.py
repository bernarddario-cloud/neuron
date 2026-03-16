"""
NEURON Network Layer — Async P2P Messaging
Handles all node-to-node communication via TCP with async I/O.
"""

import asyncio
import json
import uuid
import time
import logging
from typing import Dict, Optional, Callable, Any

logger = logging.getLogger("neuron.network")


class Message:
    """A network message between NEURON nodes."""

    def __init__(self, msg_type: str, payload: dict, sender: str = "",
                 msg_id: str = None, reply_to: str = None):
        self.id = msg_id or str(uuid.uuid4())[:12]
        self.type = msg_type
        self.payload = payload
        self.sender = sender
        self.reply_to = reply_to
        self.timestamp = time.time()

    def serialize(self) -> bytes:
        data = {
            "id": self.id, "type": self.type, "payload": self.payload,
            "sender": self.sender, "reply_to": self.reply_to,
            "timestamp": self.timestamp
        }
        raw = json.dumps(data).encode()
        return len(raw).to_bytes(4, "big") + raw

    @classmethod
    def deserialize(cls, data: bytes) -> "Message":
        obj = json.loads(data)
        msg = cls(obj["type"], obj["payload"], obj.get("sender", ""))
        msg.id = obj["id"]
        msg.reply_to = obj.get("reply_to")
        msg.timestamp = obj.get("timestamp", time.time())
        return msg


class PeerConnection:
    """Manages a single peer connection."""

    def __init__(self, peer_id: str, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter, address: tuple):
        self.peer_id = peer_id
        self.reader = reader
        self.writer = writer
        self.address = address
        self.connected_at = time.time()
        self.last_seen = time.time()
        self.messages_sent = 0
        self.messages_received = 0

    async def send(self, message: Message):
        try:
            self.writer.write(message.serialize())
            await self.writer.drain()
            self.messages_sent += 1
        except Exception as e:
            logger.error(f"Send error to {self.peer_id}: {e}")
            raise

    async def receive(self) -> Optional[Message]:
        try:
            length_bytes = await self.reader.readexactly(4)
            length = int.from_bytes(length_bytes, "big")
            data = await self.reader.readexactly(length)
            msg = Message.deserialize(data)
            self.last_seen = time.time()
            self.messages_received += 1
            return msg
        except asyncio.IncompleteReadError:
            return None
        except Exception as e:
            logger.error(f"Receive error from {self.peer_id}: {e}")
            return None

    async def close(self):
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except: pass

    @property
    def is_alive(self) -> bool:
        return time.time() - self.last_seen < 60


class NetworkNode:
    """Core networking: listens for connections and manages peer pool."""

    def __init__(self, node_id: str, host: str = "0.0.0.0", port: int = 8400):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.peers: Dict[str, PeerConnection] = {}
        self.handlers: Dict[str, Callable] = {}
        self.server = None
        self._running = False

    def on_message(self, msg_type: str):
        """Decorator to register message handlers."""
        def decorator(func):
            self.handlers[msg_type] = func
            return func
        return decorator

    def register_handler(self, msg_type: str, handler: Callable):
        self.handlers[msg_type] = handler

    async def start(self):
        self.server = await asyncio.start_server(
            self._handle_connection, self.host, self.port)
        self._running = True
        logger.info(f"Node {self.node_id} listening on {self.host}:{self.port}")

    async def stop(self):
        self._running = False
        for peer in list(self.peers.values()):
            await peer.close()
        self.peers.clear()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        logger.info(f"Node {self.node_id} stopped")

    async def connect_to(self, host: str, port: int) -> Optional[PeerConnection]:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            # Send handshake
            handshake = Message("handshake", {"node_id": self.node_id, "port": self.port}, self.node_id)
            writer.write(handshake.serialize())
            await writer.drain()

            # Wait for handshake response
            length_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=10)
            length = int.from_bytes(length_bytes, "big")
            data = await asyncio.wait_for(reader.readexactly(length), timeout=10)
            response = Message.deserialize(data)

            peer_id = response.payload.get("node_id", f"{host}:{port}")
            peer = PeerConnection(peer_id, reader, writer, (host, port))
            self.peers[peer_id] = peer
            logger.info(f"Connected to peer {peer_id} at {host}:{port}")

            # Start listening for messages from this peer
            asyncio.create_task(self._listen(peer))
            return peer
        except Exception as e:
            logger.error(f"Failed to connect to {host}:{port}: {e}")
            return None

    async def broadcast(self, message: Message):
        """Send message to all connected peers."""
        message.sender = self.node_id
        dead_peers = []
        for peer_id, peer in self.peers.items():
            try:
                await peer.send(message)
            except:
                dead_peers.append(peer_id)
        for pid in dead_peers:
            self.peers.pop(pid, None)

    async def send_to(self, peer_id: str, message: Message) -> bool:
        message.sender = self.node_id
        peer = self.peers.get(peer_id)
        if not peer:
            logger.warning(f"Peer {peer_id} not found")
            return False
        try:
            await peer.send(message)
            return True
        except:
            self.peers.pop(peer_id, None)
            return False

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        try:
            # Read handshake
            length_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=10)
            length = int.from_bytes(length_bytes, "big")
            data = await asyncio.wait_for(reader.readexactly(length), timeout=10)
            handshake = Message.deserialize(data)

            peer_id = handshake.payload.get("node_id", str(addr))
            # Send handshake response
            response = Message("handshake_ack", {"node_id": self.node_id}, self.node_id)
            writer.write(response.serialize())
            await writer.drain()

            peer = PeerConnection(peer_id, reader, writer, addr)
            self.peers[peer_id] = peer
            logger.info(f"Peer {peer_id} connected from {addr}")

            await self._listen(peer)
        except Exception as e:
            logger.debug(f"Connection error from {addr}: {e}")
            writer.close()

    async def _listen(self, peer: PeerConnection):
        while self._running:
            msg = await peer.receive()
            if msg is None:
                break
            handler = self.handlers.get(msg.type)
            if handler:
                try:
                    await handler(msg, peer)
                except Exception as e:
                    logger.error(f"Handler error for {msg.type}: {e}")
            else:
                logger.debug(f"No handler for message type: {msg.type}")
        # Peer disconnected
        self.peers.pop(peer.peer_id, None)
        logger.info(f"Peer {peer.peer_id} disconnected")

    @property
    def peer_count(self) -> int:
        return len(self.peers)

    def status(self) -> dict:
        return {
            "node_id": self.node_id,
            "address": f"{self.host}:{self.port}",
            "peers": self.peer_count,
            "running": self._running,
            "peer_list": [
                {"id": p.peer_id, "address": p.address,
                 "sent": p.messages_sent, "received": p.messages_received,
                 "alive": p.is_alive}
                for p in self.peers.values()
            ]
        }
