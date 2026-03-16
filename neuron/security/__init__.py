"""
NEURON Security — Authentication + Message Signing
Token-based auth, HMAC message signing, and rate limiting.
"""

import hashlib
import hmac
import os
import time
import json
import secrets
import logging
from typing import Dict, Optional, Set

logger = logging.getLogger("neuron.security")


class Token:
    """Authentication token for a node."""

    def __init__(self, node_id: str, secret: str = None, expires_in: int = 3600):
        self.node_id = node_id
        self.secret = secret or secrets.token_hex(32)
        self.created_at = time.time()
        self.expires_at = self.created_at + expires_in
        self.token_id = secrets.token_hex(8)

    @property
    def is_valid(self) -> bool:
        return time.time() < self.expires_at

    def sign(self, data: str) -> str:
        return hmac.new(self.secret.encode(), data.encode(), hashlib.sha256).hexdigest()

    def verify(self, data: str, signature: str) -> bool:
        expected = self.sign(data)
        return hmac.compare_digest(expected, signature)

    def to_dict(self) -> dict:
        return {
            "token_id": self.token_id, "node_id": self.node_id,
            "created_at": self.created_at, "expires_at": self.expires_at
        }


class SecurityManager:
    """Manages node authentication and message integrity."""

    def __init__(self, node_id: str, cluster_secret: str = None):
        self.node_id = node_id
        self.cluster_secret = cluster_secret or secrets.token_hex(32)
        self.tokens: Dict[str, Token] = {}
        self.banned: Set[str] = set()
        self.rate_limits: Dict[str, list] = {}
        self.max_requests_per_minute = 120

    def generate_token(self, peer_id: str, expires_in: int = 3600) -> Token:
        token = Token(peer_id, expires_in=expires_in)
        self.tokens[peer_id] = token
        logger.info(f"Token generated for {peer_id} (expires in {expires_in}s)")
        return token

    def authenticate(self, peer_id: str, token_secret: str) -> bool:
        if peer_id in self.banned:
            logger.warning(f"Banned node tried to auth: {peer_id}")
            return False
        token = self.tokens.get(peer_id)
        if not token:
            return False
        if not token.is_valid:
            self.tokens.pop(peer_id, None)
            return False
        return hmac.compare_digest(token.secret, token_secret)

    def sign_message(self, data: str) -> str:
        return hmac.new(
            self.cluster_secret.encode(), data.encode(), hashlib.sha256
        ).hexdigest()

    def verify_message(self, data: str, signature: str) -> bool:
        expected = self.sign_message(data)
        return hmac.compare_digest(expected, signature)

    def check_rate_limit(self, peer_id: str) -> bool:
        now = time.time()
        if peer_id not in self.rate_limits:
            self.rate_limits[peer_id] = []
        # Clean old entries
        self.rate_limits[peer_id] = [t for t in self.rate_limits[peer_id] if now - t < 60]
        if len(self.rate_limits[peer_id]) >= self.max_requests_per_minute:
            logger.warning(f"Rate limit exceeded for {peer_id}")
            return False
        self.rate_limits[peer_id].append(now)
        return True

    def ban(self, peer_id: str, reason: str = ""):
        self.banned.add(peer_id)
        self.tokens.pop(peer_id, None)
        logger.warning(f"Banned node {peer_id}: {reason}")

    def unban(self, peer_id: str):
        self.banned.discard(peer_id)

    def rotate_cluster_secret(self) -> str:
        old = self.cluster_secret
        self.cluster_secret = secrets.token_hex(32)
        logger.info("Cluster secret rotated")
        return self.cluster_secret

    def status(self) -> dict:
        active_tokens = sum(1 for t in self.tokens.values() if t.is_valid)
        return {
            "node_id": self.node_id,
            "active_tokens": active_tokens,
            "total_tokens": len(self.tokens),
            "banned_nodes": len(self.banned),
            "rate_limited_peers": len(self.rate_limits)
        }
