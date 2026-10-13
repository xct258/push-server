"""运行：python3 -m unittest discover -s tests -v。数据与 HTTP 均隔离。"""
import asyncio
import importlib.util
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from urllib.error import HTTPError

from starlette.requests import Request


class TaskCancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.backends = []
        for source in ("容器相关脚本/main.py", "data/main.py"):
            if not (root / source).exists():
                continue
            spec = importlib.util.spec_from_file_location("push_cancellation_test", root / source)
            backend = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(backend)
            cls.backends.append((source, backend))

    def task(self, **fields):
        task = dict(task_id=7, client_ref="todo-123", server_name="taskops", status="sent",
                    callback="none", retry=0, schedule_at="2026-10-12T20:30:00+08:00")
        task.update(fields)
        return task

    @contextmanager
    def storage(self, backend, tasks):
        with patch.object(backend, "load_tasks", return_value={"tasks": tasks}), \
             patch.object(backend, "save_tasks") as save, \
             patch.object(backend, "PUSH_SERVER_TOKEN", ""):
            yield save

    def test_source_cancellation_never_calls_taskops(self):
        for source, backend in self.backends:
            with self.subTest(source=source):
                task = self.task(callback="pending", retry=4)
                other = self.task(task_id=8, server_name="other")
                with self.storage(backend, [task, other]) as save, \
                     patch.object(backend, "do_callback", new_callable=AsyncMock) as callback:
                    result = asyncio.run(backend.cancel_task_by_ref(
                        "todo-123", Request({"type": "http", "headers": []}), "taskops",
                    ))
                    self.assertEqual(result["cancelled"], 1)
                    self.assertEqual(task["status"], "cancelled")
                    self.assertEqual(task["callback"], "none")
                    self.assertEqual(task["retry"], 0)
                    self.assertEqual(other["status"], "sent")
                    callback.assert_not_called()
                    save.assert_called_once()

    def test_repeat_cancellation_clears_stale_retry(self):
        for source, backend in self.backends:
            with self.subTest(source=source):
                task = self.task(status="cancelled", callback="pending", retry=4)
                with self.storage(backend, [task]) as save:
                    result = asyncio.run(backend.cancel_task_by_ref(
                        "todo-123", Request({"type": "http", "headers": []}), "taskops",
                    ))
                    self.assertEqual(result["cancelled"], 0)
                    self.assertEqual(task["callback"], "none")
                    self.assertEqual(task["retry"], 0)
                    save.assert_called_once()

    def test_manual_cancel_still_reports_processed_to_taskops(self):
        for source, backend in self.backends:
            with self.subTest(source=source):
                self.assertEqual(backend.FeedbackIn(action="cancelled").action, "cancelled")
                task = self.task()
                callbacks = []

                async def cancel():
                    with patch.object(backend.asyncio, "create_task", side_effect=callbacks.append):
                        result = await backend.apply_feedback(7, "cancelled")
                    self.assertEqual(result["status"], "cancelled")
                    for callback in callbacks:
                        await callback

                with self.storage(backend, [task]), \
                     patch.object(backend, "_callback_http", return_value={}) as http:
                    asyncio.run(cancel())
                    http.assert_called_once()
                    self.assertEqual(http.call_args.args[0], "PUT")
                    self.assertEqual(http.call_args.args[1], f"{backend.TASKOPS_BASE_URL}/api/todos/123/processed")
                    self.assertEqual(http.call_args.args[2]["action"], "cancelled")
                    self.assertTrue(http.call_args.args[2]["callback_ref"])
                    self.assertEqual(task["callback"], "done")

    def test_deleted_todo_404_stops_retries(self):
        for source, backend in self.backends:
            with self.subTest(source=source):
                task = self.task(status="done")
                with self.storage(backend, [task]), \
                     patch.object(backend, "_callback_http", side_effect=HTTPError("test", 404, "not found", {}, None)) as http, \
                     patch.object(backend.asyncio, "sleep", new_callable=AsyncMock) as sleep:
                    asyncio.run(backend.do_callback(dict(task), "done"))
                    http.assert_called_once()
                    sleep.assert_not_called()
                    self.assertEqual(task["callback"], "skipped")
                    self.assertEqual(task["retry"], 0)

    def test_transient_failure_still_retries(self):
        for source, backend in self.backends:
            with self.subTest(source=source):
                task = self.task(status="done")
                http = Mock(side_effect=[HTTPError("test", 503, "unavailable", {}, None), {}])
                with self.storage(backend, [task]), patch.object(backend, "_callback_http", http), \
                     patch.object(backend.asyncio, "sleep", new_callable=AsyncMock) as sleep:
                    asyncio.run(backend.do_callback(dict(task), "done"))
                    self.assertEqual(http.call_count, 2)
                    sleep.assert_awaited_once_with(30)
                    self.assertEqual(task["callback"], "done")

    def test_source_cancellation_stops_old_snooze_callback(self):
        for source, backend in self.backends:
            with self.subTest(source=source):
                snapshot = self.task(status="pending")
                task = self.task(status="cancelled")
                with self.storage(backend, [task]), patch.object(backend, "_callback_http") as http:
                    asyncio.run(backend.do_callback(snapshot, "snooze"))
                    http.assert_not_called()
                    self.assertEqual(task["callback"], "none")

    def test_snooze_callback_uses_mqtt_at(self):
        for source, backend in self.backends:
            with self.subTest(source=source):
                task = self.task()
                with self.storage(backend, [task]), \
                     patch.object(backend, "_callback_http", return_value={}) as http:
                    asyncio.run(backend.do_callback(dict(task), "snooze", {"snooze_minutes": 60}))
                    body = http.call_args.args[2]
                    self.assertEqual(body["mqtt_at"], task["schedule_at"])
                    self.assertNotIn("push_at", body)


if __name__ == "__main__":
    unittest.main()
