"""运行：python3 -m unittest discover -s tests -v。数据与 HTTP 均隔离。"""
import asyncio
import importlib.util
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request


class TaskCancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "push_cancellation_test", root / "容器相关脚本/main.py"
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        cls.backend = backend

    def task(self, **fields):
        task = dict(task_id=7, client_ref="todo-123", server_name="taskops", status="sent",
                    schedule_at="2026-10-12T20:30:00+08:00")
        task.update(fields)
        return task

    @contextmanager
    def storage(self, tasks):
        with patch.object(self.backend, "load_tasks", return_value={"tasks": tasks}), \
             patch.object(self.backend, "save_tasks") as save, \
             patch.object(self.backend, "PUSH_SERVER_TOKEN", ""):
            yield save

    def test_source_cancellation_marks_cancelled(self):
        task = self.task()
        other = self.task(task_id=8, server_name="other")
        with self.storage([task, other]) as save:
            result = asyncio.run(self.backend.cancel_task_by_ref(
                "todo-123", Request({"type": "http", "headers": []}), "taskops",
            ))
            self.assertEqual(result["cancelled"], 1)
            self.assertEqual(task["status"], "cancelled")
            self.assertEqual(other["status"], "sent")
            save.assert_called_once()

    def test_repeat_cancellation_is_noop(self):
        task = self.task(status="cancelled")
        with self.storage([task]) as save:
            result = asyncio.run(self.backend.cancel_task_by_ref(
                "todo-123", Request({"type": "http", "headers": []}), "taskops",
            ))
            self.assertEqual(result["cancelled"], 0)
            save.assert_not_called()

    def test_push_server_is_pure_one_way(self):
        backend = self.backend
        # 无回调、无反馈：函数 / 配置 / 模型全部不存在。
        for name in ("do_callback", "_callback_http", "TASKOPS_BASE_URL", "TASKOPS_TOKEN",
                     "CALLBACK_MAX_RETRY", "apply_feedback", "feedback_consumer_loop",
                     "start_feedback_subscriber", "FeedbackIn", "FEEDBACK_TOPIC"):
            self.assertFalse(hasattr(backend, name), name)

    def test_no_feedback_route(self):
        paths = {getattr(r, "path", "") for r in self.backend.app.routes}
        self.assertNotIn("/api/task/{task_id}/feedback", paths)

    def test_upsert_and_query_routes_remain(self):
        paths = {getattr(r, "path", "") for r in self.backend.app.routes}
        for path in ("/api/task", "/api/task/{task_id}", "/api/task/ref/{client_ref}", "/api/tasks"):
            self.assertIn(path, paths)


if __name__ == "__main__":
    unittest.main()
