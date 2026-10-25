"""`POST /api/push` 的 title/status 必填与落库测试。

运行：/opt/taskops-venv/bin/python -m unittest discover -s tests -v
"""
import asyncio
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError


class PushRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "push_request_test", root / "容器相关脚本/main.py"
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        cls.backend = backend

    def payload(self, **fields):
        data = dict(
            server_name="server-1",
            topic="test/topic",
            title="测试标题",
            message="hello",
            status="ok",
            push_to_mqtt=False,
        )
        data.update(fields)
        return data

    def existing_record(self, **fields):
        data = dict(
            id=5,
            server_name="server-1",
            topic="test/topic",
            title="测试标题",
            message="old",
            status="ok",
            push_to_mqtt=False,
            push_result="skipped",
            msg_type="markdown",
            mode="append",
            created_at="2026-10-20 04:00:00",
        )
        data.update(fields)
        return data

    def test_title_is_required(self):
        data = self.payload()
        data.pop("title")
        with self.assertRaises(ValidationError):
            self.backend.PushRequest(**data)

    def test_title_is_trimmed_and_must_not_be_empty(self):
        request = self.backend.PushRequest(**self.payload(title="  备份失败  "))
        self.assertEqual(request.title, "备份失败")

        with self.assertRaises(ValidationError):
            self.backend.PushRequest(**self.payload(title="   "))

    def test_status_is_required(self):
        data = self.payload()
        data.pop("status")
        with self.assertRaises(ValidationError):
            self.backend.PushRequest(**data)

    def test_status_only_accepts_known_values(self):
        for value in ("ok", "warn", "error", "info"):
            self.assertEqual(self.backend.PushRequest(**self.payload(status=value)).status, value)

        with self.assertRaises(ValidationError):
            self.backend.PushRequest(**self.payload(status="maybe"))

    def test_status_is_normalized(self):
        self.assertEqual(self.backend.PushRequest(**self.payload(status=" WARN ")).status, "warn")

    def test_status_is_saved_in_record(self):
        request = self.backend.PushRequest(**self.payload(status="error"))
        saved = {}

        def fake_save(name, records):
            saved["name"] = name
            saved["records"] = records

        with patch.object(self.backend, "load_server", return_value=[]), \
             patch.object(self.backend, "save_server", side_effect=fake_save), \
             patch.object(self.backend, "broadcast"):
            result = asyncio.run(self.backend.push_to_phone(request))

        self.assertEqual(result["status"], "error")
        self.assertEqual(saved["name"], "server-1")
        self.assertEqual(saved["records"][0]["title"], "测试标题")
        self.assertEqual(saved["records"][0]["status"], "error")

    def test_overwrite_keeps_status(self):
        existing = self.existing_record()
        request = self.backend.PushRequest(**self.payload(status="warn", mode="overwrite"))
        saved = {}

        with patch.object(self.backend, "load_server", return_value=[existing]), \
             patch.object(self.backend, "save_server", side_effect=lambda name, records: saved.update(records=records)), \
             patch.object(self.backend, "broadcast"):
            asyncio.run(self.backend.push_to_phone(request))

        self.assertEqual(len(saved["records"]), 1)
        self.assertEqual(saved["records"][0]["id"], 5)
        self.assertEqual(saved["records"][0]["title"], "测试标题")
        self.assertEqual(saved["records"][0]["status"], "warn")

    def test_overwrite_with_different_title_appends(self):
        existing = self.existing_record(title="其他脚本")
        request = self.backend.PushRequest(**self.payload(mode="overwrite"))
        saved = {}

        with patch.object(self.backend, "load_server", return_value=[existing]), \
             patch.object(self.backend, "save_server", side_effect=lambda name, records: saved.update(records=records)), \
             patch.object(self.backend, "broadcast"):
            asyncio.run(self.backend.push_to_phone(request))

        self.assertEqual(len(saved["records"]), 2)
        self.assertEqual(saved["records"][0]["title"], "其他脚本")
        self.assertEqual(saved["records"][1]["title"], "测试标题")

    def test_overwrite_with_different_topic_appends(self):
        existing = self.existing_record()
        request = self.backend.PushRequest(**self.payload(topic="test/other", mode="overwrite"))
        saved = {}

        with patch.object(self.backend, "load_server", return_value=[existing]), \
             patch.object(self.backend, "save_server", side_effect=lambda name, records: saved.update(records=records)), \
             patch.object(self.backend, "broadcast"):
            asyncio.run(self.backend.push_to_phone(request))

        self.assertEqual(len(saved["records"]), 2)
        self.assertEqual(saved["records"][1]["topic"], "test/other")


if __name__ == "__main__":
    unittest.main()
