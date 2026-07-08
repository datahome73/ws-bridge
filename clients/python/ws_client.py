"""WS Bridge client — reusable async WebSocket client library (R72+).

Features:
  - R72 new auth: register → api_key → agent_card_register → auth(api_key)
  - Credential management via ``~/.ws-bridge/{name}.json``
  - WebSocket-level ping/pong keep-alive (ping_interval=20)
  - Automatic reconnection with exponential backoff
  - on_connect / on_disconnect / on_message callbacks
  - send_message returns a unique message ID
  - Thread-safe message deduplication via seen_ids
  - ACK waiting + retry on timeout
  - Offline catchup via last_seen_ts (persisted to JSON file)
  - Inbox message protocol (R82+):
    All received messages are inbox messages.
    Reply = send_message(content, channel=f"_inbox:{sender_agent_id}")
    sender_agent_id from msg.agent_id or msg.from_agent.
    See docs/inbox-message-protocol.md for details.

Inbox 消息协议（R82+）：
所有收到的消息都是 inbox 消息。
回复 = send_message(content, channel=f"_inbox:{sender_agent_id}")
sender_agent_id 从 msg.agent_id 或 msg.from_agent 获取。
详见 docs/inbox-message-protocol.md
"""