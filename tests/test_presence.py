"""客户端在线状态（`$presence/clients/#`）的解析与 API 测试。

运行：python -m unittest discover -s tests -v
"""
import asyncio
import importlib.util
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


class PresenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "presence_test", root / "容器相关脚本/main.py"
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        cls.backend = backend

    def test_retained_online_payload_is_stored(self):
        tracker = self.backend.PresenceTracker()

        tracker.ingest("windows_a", online=True, platform="windows", name="PC", version="1.0.0")
        clients = tracker.snapshot()

        self.assertEqual(1, len(clients))
        self.assertTrue(clients[0]["online"])
        self.assertEqual("windows_a", clients[0]["client_id"])
        self.assertEqual("windows", clients[0]["platform"])
        self.assertIn("last_seen_epoch", clients[0])

    def test_offline_payload_wins(self):
        tracker = self.backend.PresenceTracker()
        tracker.ingest("android_a", online=True, platform="android")
        tracker.ingest("android_a", online=False, platform="android")

        self.assertFalse(tracker.snapshot()[0]["online"])

    def test_late_will_with_old_ts_is_ignored(self):
        """重连后旧连接的 Will 可能迟到；它的 ts 是连接开始时间，不能覆盖新心跳。"""
        tracker = self.backend.PresenceTracker()
        tracker.ingest("android_a", online=True, platform="android", client_ts=200.0)
        tracker.ingest("android_a", online=False, platform="android", client_ts=100.0)

        self.assertTrue(tracker.snapshot()[0]["online"])

    def test_intentional_offline_with_new_ts_wins(self):
        """正常停止时重新生成的离线 payload ts 更新，应立刻生效。"""
        tracker = self.backend.PresenceTracker()
        tracker.ingest("android_a", online=True, platform="android", client_ts=100.0)
        tracker.ingest("android_a", online=False, platform="android", client_ts=200.0)

        self.assertFalse(tracker.snapshot()[0]["online"])

    def test_presence_ts_parser_accepts_iso_and_rejects_garbage(self):
        parse = self.backend.parse_presence_ts
        self.assertGreater(parse("2026-11-06T12:55:32.382079+08:00"), 0)
        self.assertGreater(parse("2026-11-06T04:55:32Z"), 0)
        self.assertEqual(0.0, parse("not-a-time"))
        self.assertEqual(0.0, parse(None))

    def test_stale_heartbeat_is_reported_offline(self):
        tracker = self.backend.PresenceTracker(ttl_seconds=10)
        tracker.ingest("windows_a", online=True, platform="windows")

        with tracker._lock:
            tracker._items["a"]["last_seen_ts"] -= 11

        self.assertFalse(tracker.snapshot()[0]["online"])

    def test_message_topic_fallback_and_json_fields(self):
        tracker = self.backend.PresenceTracker()
        payload = json.dumps(
            {
                "client_id": "android_1",
                "suffix": "1",
                "name": "Pixel 9",
                "platform": "android",
                "version": "1.0.0",
                "topic": "taskops/todo/#",
                "online": True,
            }
        ).encode("utf-8")

        tracker._on_message(
            None,
            None,
            SimpleNamespace(topic="$presence/clients/android_1", payload=payload),
        )

        client = tracker.snapshot()[0]
        self.assertEqual("android_1", client["client_id"])
        self.assertEqual("Pixel 9", client["name"])
        self.assertEqual("taskops/todo/#", client["topic"])
        self.assertTrue(client["online"])

    def test_same_suffix_represents_same_device(self):
        tracker = self.backend.PresenceTracker()
        tracker.ingest("android_abc12345", online=True, platform="android", name="Pixel")
        tracker.ingest("my-phone_abc12345", online=True, platform="android", name="Pixel 9")

        clients = tracker.snapshot()
        self.assertEqual(1, len(clients))
        self.assertEqual("my-phone_abc12345", clients[0]["client_id"])
        self.assertEqual("abc12345", clients[0]["suffix"])
        self.assertEqual("Pixel 9", clients[0]["name"])


    def test_status_change_time_only_updates_on_transition(self):
        tracker = self.backend.PresenceTracker()
        tracker.ingest("android_a", online=True, platform="android")
        first = tracker._items["a"]["status_changed_ts"]

        time.sleep(0.02)
        tracker.ingest("android_a", online=True, platform="android")
        self.assertEqual(first, tracker._items["a"]["status_changed_ts"])

        time.sleep(0.02)
        tracker.ingest("android_a", online=False, platform="android")
        self.assertGreater(tracker._items["a"]["status_changed_ts"], first)
        self.assertIn("status_changed_epoch", tracker.snapshot()[0])

    def test_old_hyphen_payload_is_ignored(self):
        tracker = self.backend.PresenceTracker()
        tracker._on_message(
            None,
            None,
            SimpleNamespace(
                topic="$presence/clients/my-phone-abc12345",
                payload=json.dumps(
                    {
                        "client_id": "my-phone-abc12345",
                        "platform": "android",
                        "online": True,
                    }
                ).encode("utf-8"),
            ),
        )

        self.assertEqual([], tracker.snapshot())

    def test_delete_offline_then_reconnect_restores(self):
        tracker = self.backend.PresenceTracker()
        tracker.ingest("android_abc12345", online=False, platform="android")
        old_tracker = self.backend._presence_tracker
        self.backend._presence_tracker = tracker
        try:
            deleted = asyncio.run(self.backend.delete_client("abc12345"))
            self.assertEqual("abc12345", deleted["deleted"])
            self.assertEqual([], tracker.snapshot())

            tracker.ingest("android_abc12345", online=True, platform="android")
            self.assertTrue(tracker.snapshot()[0]["online"])
        finally:
            self.backend._presence_tracker = old_tracker

    def test_online_client_cannot_be_deleted(self):
        tracker = self.backend.PresenceTracker()
        tracker.ingest("android_abc12345", online=True, platform="android")
        old_tracker = self.backend._presence_tracker
        self.backend._presence_tracker = tracker
        try:
            with self.assertRaises(self.backend.HTTPException) as ctx:
                asyncio.run(self.backend.delete_client("abc12345"))
            self.assertEqual(409, ctx.exception.status_code)
        finally:
            self.backend._presence_tracker = old_tracker

    def test_empty_retained_payload_removes_client(self):
        tracker = self.backend.PresenceTracker()
        tracker.ingest(
            "android_a",
            online=True,
            platform="android",
            presence_topic="$presence/clients/android_a",
        )

        tracker._on_message(
            None,
            None,
            SimpleNamespace(topic="$presence/clients/android_a", payload=b""),
        )

        self.assertEqual([], tracker.snapshot())

    def test_clearing_old_topic_keeps_new_prefix_record(self):
        tracker = self.backend.PresenceTracker()
        tracker._clear_retained = lambda topic: None
        tracker.ingest(
            "old_abcd1234",
            online=True,
            platform="windows",
            presence_topic="$presence/clients/old_abcd1234",
        )
        tracker.ingest(
            "new_abcd1234",
            online=True,
            platform="windows",
            presence_topic="$presence/clients/new_abcd1234",
        )

        # 后端清理旧前缀时，broker 会把空 retained 回投给订阅端
        tracker._on_message(
            None,
            None,
            SimpleNamespace(topic="$presence/clients/old_abcd1234", payload=b""),
        )

        clients = tracker.snapshot()
        self.assertEqual(1, len(clients))
        self.assertEqual("new_abcd1234", clients[0]["client_id"])

    def test_api_sorts_online_first_and_filters(self):
        tracker = self.backend.PresenceTracker()
        tracker.ingest("offline-b", online=False, platform="windows")
        tracker.ingest("online-a", online=True, platform="android")
        old_tracker = self.backend._presence_tracker
        self.backend._presence_tracker = tracker
        try:
            result = asyncio.run(self.backend.list_clients(online=None))
            online_only = asyncio.run(self.backend.list_clients(online=True))
        finally:
            self.backend._presence_tracker = old_tracker

        self.assertEqual(2, result["total"])
        self.assertEqual(1, result["online"])
        self.assertEqual("online-a", result["clients"][0]["client_id"])
        self.assertEqual(1, online_only["total"])
        self.assertEqual("online-a", online_only["clients"][0]["client_id"])


if __name__ == "__main__":
    unittest.main()
