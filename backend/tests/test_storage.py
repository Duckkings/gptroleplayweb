import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.storage import _should_reset_path_to_default, read_json, write_json_atomic


class StorageCoreTests(unittest.TestCase):
    def test_write_json_atomic_retries_transient_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            real_replace = type(path).replace
            attempts = {"count": 0}

            def flaky_replace(self: Path, target: Path) -> Path:
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise PermissionError("locked")
                return real_replace(self, target)

            with patch.object(type(path), "replace", autospec=True, side_effect=flaky_replace), patch(
                "app.core.storage.time.sleep",
                return_value=None,
            ):
                write_json_atomic(path, {"ok": True})

            self.assertEqual(attempts["count"], 2)
            self.assertEqual(read_json(path), {"ok": True})

    def test_should_reset_path_to_default_for_backend_tmp_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend_tmp_root = root / "backend" / ".tmp_test"
            candidate = backend_tmp_root / "debug_case" / "current-save.json"
            self.assertTrue(
                _should_reset_path_to_default(
                    candidate,
                    temp_root=root / "system_tmp",
                    backend_tmp_root=backend_tmp_root,
                )
            )

    def test_should_not_reset_existing_normal_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate = root / "saves" / "current-save.json"
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text("{}", encoding="utf-8")
            self.assertFalse(
                _should_reset_path_to_default(
                    candidate,
                    temp_root=root / "system_tmp",
                    backend_tmp_root=root / "backend" / ".tmp_test",
                )
            )


if __name__ == "__main__":
    unittest.main()
