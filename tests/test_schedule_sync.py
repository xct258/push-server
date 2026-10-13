"""计划同步回归测试：隔离任务库与 MQTT，不发送外部请求。"""
import asyncio
import importlib.util
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

spec = importlib.util.spec_from_file_location("schedule_backend", Path(__file__).resolve().parents[1] / "容器相关脚本/main.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class ScheduleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(backend, "TASKS_PATH", str(Path(self.temp.name) / "tasks.json")).start()
        patch.object(backend, "PUSH_SERVER_TOKEN", "").start()
        self.callback = patch.object(backend, "do_callback", new_callable=AsyncMock).start()
        self.request = Request({"type": "http", "headers": []})

    async def create(self, ref="todo-123"):
        return await backend.upsert_task(backend.TaskCreate(
            server_name="taskops", client_ref=ref, title="整理工具柜", message="清点工具",
            schedule_at=backend._now_shanghai() + timedelta(days=1)), self.request)

    async def test_registration_and_idempotent_upsert(self):
        result = await self.create()
        task = backend.load_tasks()["tasks"][0]
        self.assertEqual(task["revision"], 1)
        self.assertEqual(task["change"]["action"], "created")
        repeated = await backend.upsert_task(backend.TaskCreate(
            server_name="taskops", client_ref="todo-123", title=task["title"], message=task["message"],
            schedule_at=task["schedule_at"]), self.request)
        self.assertEqual(repeated["action"], "unchanged")
        self.assertEqual(backend.load_tasks()["snapshot_version"], 1)
        self.assertEqual(result["task_id"], repeated["task_id"])

    async def test_snooze_receipt_and_stale_device(self):
        result = await self.create()
        first = await backend.apply_feedback(result["task_id"], "snooze", 60, 1, "req-1", "phone-a", "手机 A")
        replay = await backend.apply_feedback(result["task_id"], "snooze", 60, 1, "req-1", "phone-a", "手机 A")
        self.assertEqual(first, replay)
        conflict = await backend.apply_feedback(result["task_id"], "done", 60, 1, "req-2", "phone-b")
        self.assertEqual(conflict["code"], 409)
        task = backend.load_tasks()["tasks"][0]
        self.assertEqual(task["revision"], 2)
        self.assertEqual(task["change"]["device_name"], "手机 A")
        await asyncio.sleep(0)
        self.callback.assert_awaited_once()

    async def test_source_done_and_new_period(self):
        result = await self.create()
        await backend.sync_task_state(result["task_id"], backend.TaskStateIn(status="done"), self.request)
        snapshot = await backend.list_schedules(self.request, "taskops")
        self.assertEqual(snapshot["tasks"], [])
        self.assertEqual(snapshot["terminal_tasks"][0]["status"], "done")
        self.callback.assert_not_called()
        new = await self.create()
        self.assertNotEqual(new["task_id"], result["task_id"])
        repeated = await self.create()
        self.assertEqual(new["task_id"], repeated["task_id"])

    async def test_snapshot_not_truncated_and_sent_stays_active(self):
        data = backend._empty_tasks()
        data["tasks"] = [dict(task_id=i, server_name="taskops", client_ref=f"todo-{i}",
            status="sent", title="提醒", message="", schedule_at=backend._now_str()) for i in range(150)]
        backend.save_tasks(data)
        snapshot = await backend.list_schedules(self.request, "taskops")
        self.assertEqual(len(snapshot["tasks"]), 150)
        self.assertEqual(snapshot["tasks"][0]["status"], "active")

    async def run_sync(self, publish_mock):
        loop = asyncio.create_task(backend.schedule_sync_loop())
        try:
            for _ in range(100):
                await asyncio.sleep(0.01)
                task = backend.load_tasks()["tasks"][0]
                if task.get("schedule_sync_revision") or task.get("schedule_sync_retry"):
                    break
            else:
                self.fail("计划发布未完成")
        finally:
            loop.cancel()
            await asyncio.gather(loop, return_exceptions=True)

    async def test_retained_publish_and_failed_retry(self):
        await self.create()
        with patch.object(backend.publish, "single") as publish:
            await self.run_sync(publish)
            args = publish.call_args.kwargs
            self.assertTrue(args["retain"])
            self.assertEqual(args["qos"], 1)
            self.assertEqual(json.loads(args["payload"])["revision"], 1)
        data = backend.load_tasks()
        data["tasks"][0]["schedule_sync_revision"] = 0
        backend.save_tasks(data)
        with patch.object(backend.publish, "single", side_effect=OSError("offline")) as publish:
            await self.run_sync(publish)
        task = backend.load_tasks()["tasks"][0]
        self.assertEqual(task["schedule_sync_retry"], 1)
        self.assertIsNotNone(task["schedule_sync_next_at"])

    async def test_cancel_publishes_terminal_and_expiry_clears_retained(self):
        result = await self.create()
        await backend.cancel_task_by_ref("todo-123", self.request, "taskops")
        with patch.object(backend.publish, "single") as publish:
            await self.run_sync(publish)
            self.assertEqual(json.loads(publish.call_args.kwargs["payload"])["status"], "cancelled")
        data = backend.load_tasks()
        data["tasks"][0]["terminal_at"] = (backend._now_shanghai() - timedelta(days=8)).isoformat()
        data["tasks"][0]["schedule_sync_revision"] = 0
        backend.save_tasks(data)
        with patch.object(backend.publish, "single") as publish:
            await self.run_sync(publish)
            self.assertEqual(publish.call_args.kwargs["payload"], b"")
