"""WS Bridge reusable client library.

Provides:
  - :class:`WsBridgeClient` — low-level async WebSocket client
  - :class:`HermesWsBridgeAdapter` — deployable adapter with message processing
"""

from .hermes_adapter import AdapterConfig, HermesWsBridgeAdapter
from .ws_client import WsBridgeClient

__all__ = [
    "WsBridgeClient",
    "HermesWsBridgeAdapter",
    "AdapterConfig",
]
