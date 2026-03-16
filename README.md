# NEURON — Distributed Computing Platform

A decentralized network of computational nodes for distributed task execution, dynamic resource allocation, and secure peer-to-peer communication.

## Architecture

```
┌──────────────────────────────────────────────────┐
│               NEURON ORCHESTRATOR                │
│  Central coordinator for all subsystems          │
├──────────┬──────────┬──────────┬────────────────┤
│ NETWORK  │  TASKS   │RESOURCES │   SECURITY     │
│ P2P comm │ Distrib. │ CPU/Mem  │   Auth/Enc     │
│ Async IO │ Queue    │ Monitor  │   TLS/Tokens   │
├──────────┴──────┬───┴──────────┴────────────────┤
│   DISCOVERY     │        LOAD BALANCER           │
│   Peer finding  │   Smart work distribution      │
│   Health checks │   Capacity-aware routing        │
└─────────────────┴────────────────────────────────┘
```

## Modules

| Module | Description |
|--------|------------|
| `neuron.network` | Async P2P messaging, connection pool, message routing |
| `neuron.discovery` | Peer discovery via broadcast, registry, and heartbeats |
| `neuron.tasks` | Task serialization, distribution, results aggregation |
| `neuron.resources` | CPU/memory/disk monitoring, capacity reporting |
| `neuron.security` | Token auth, message signing, encrypted channels |
| `neuron.balancer` | Load-aware task routing, weighted distribution |

## Quick Start

```bash
# Install
pip install -e .

# Start a node
neuron start --port 8400 --name worker-1

# Join a network
neuron join --seed 192.168.1.10:8400

# Submit a task
neuron submit --task "compute" --payload '{"fn": "sum", "data": [1,2,3]}'

# Check cluster status
neuron status
```

## Configuration

```yaml
# config/neuron.yaml
node:
  name: worker-1
  port: 8400
  role: worker  # worker | coordinator | hybrid

network:
  max_peers: 50
  heartbeat_interval: 10
  message_timeout: 30

security:
  auth_enabled: true
  encryption: aes-256-gcm
  token_expiry: 3600

resources:
  cpu_threshold: 85
  memory_threshold: 90
  report_interval: 5
```

## License

MIT — Bernard Dario
