from __future__ import annotations

import json

from duedatehq.core.session_manager import RedisInteractionSessionManager


class FakeRedis:
    def __init__(self):
        self.values = {}

    def setex(self, key, ttl, value):
        self.values[key] = {"ttl": ttl, "value": value}

    def get(self, key):
        item = self.values.get(key)
        return None if item is None else item["value"].encode("utf-8")


def test_redis_session_manager_round_trips_session():
    client = FakeRedis()
    manager = RedisInteractionSessionManager("redis://example", ttl_seconds=10, client=client)

    session = manager.start("tenant-1", today="2026-04-26", session_id="session-1")
    session["history_window"].append({"actor": "user", "text": "hi"})
    manager.save(session)
    loaded = manager.get("session-1")

    assert loaded["tenant_id"] == "tenant-1"
    assert loaded["history_window"][0]["text"] == "hi"
    assert client.values["duedatehq:session:session-1"]["ttl"] == 10
    assert json.loads(client.values["duedatehq:session:session-1"]["value"])["today"] == "2026-04-26"
