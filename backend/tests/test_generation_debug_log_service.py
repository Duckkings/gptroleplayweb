import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.storage import storage_state
from app.core.user_context import get_current_user, set_current_user
from app.services.generation_debug_log_service import generation_debug_log


class GenerationDebugLogServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        self._orig_user = get_current_user()
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))
        set_current_user(None)
        self._log_path = root / "debug" / "latest-generation-log.json"

    def tearDown(self) -> None:
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        set_current_user(self._orig_user)
        self._tmpdir.cleanup()

    def test_latest_log_overwrites_previous_run(self) -> None:
        with generation_debug_log("main_chat", "sess_one", {"last_user_preview": "first"}) as log:
            log.record("phase", "prepare", {"detail": "first"})
            log.finish(status="success", result={"reply_preview": "ok"})

        with generation_debug_log("map_move_zone", "sess_two", {"to_zone_id": "zone_b"}) as log:
            log.record("phase", "prepare", {"detail": "second"})
            log.finish(status="error", error={"message": "boom"})

        payload = json.loads(self._log_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["flow_kind"], "map_move_zone")
        self.assertEqual(payload["session_id"], "sess_two")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["request"]["to_zone_id"], "zone_b")
        self.assertEqual(len(payload["events"]), 1)

    def test_context_records_error_when_exception_escapes(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "forced failure"):
            with generation_debug_log("npc_chat", "sess_err", {"npc_role_id": "npc_1"}) as log:
                log.record("phase", "model_reply", {"detail": "running"})
                raise RuntimeError("forced failure")

        payload = json.loads(self._log_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["flow_kind"], "npc_chat")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["type"], "RuntimeError")
        self.assertIn("forced failure", payload["error"]["message"])

    def test_permission_error_does_not_abort_log_updates(self) -> None:
        with patch("app.services.generation_debug_log_service.write_json_atomic", side_effect=PermissionError("locked")):
            with generation_debug_log("main_chat", "sess_locked", {"last_user_preview": "locked"}) as log:
                log.record("phase", "tool_plan", {"detail": "running"})
                log.finish(status="success", result={"reply_preview": "ok"})

        payload = json.loads(self._log_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["flow_kind"], "main_chat")
        self.assertEqual(payload["session_id"], "sess_locked")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["log_write_warning"]["message"], "locked")


if __name__ == "__main__":
    unittest.main()
