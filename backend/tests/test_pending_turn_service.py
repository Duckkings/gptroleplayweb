import tempfile
import unittest
from pathlib import Path

from app.core.storage import storage_state
from app.models.schemas import PendingTurnState, PlayerReactionCheck
from app.services.pending_turn_service import cancel_pending_turn, clear_pending_turn, load_pending_turn, save_pending_turn


def _sample_reaction() -> PlayerReactionCheck:
    return PlayerReactionCheck(
        reaction_id="react_1",
        source_kind="npc_action",
        source_actor_id="npc_1",
        source_actor_name="醉汉",
        source_label="醉汉",
        trigger_summary="醉汉抬手朝你打来。",
        threatened_consequence="你可能被打中并陷入被动。",
        ability_used="dexterity",
        dc=12,
        check_task="躲开迎面打来的巴掌",
        resolution_context="main_chat",
        success_hint="你及时偏头躲开。",
        failure_hint="你被一巴掌打中。",
        critical_success_hint="你不但躲开，还反过来稳住场面。",
        critical_failure_hint="你结结实实挨了一下。",
    )


class PendingTurnServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))

    def tearDown(self) -> None:
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        self._tmpdir.cleanup()

    def test_save_and_load_pending_turn(self) -> None:
        state = PendingTurnState(
            pending_turn_id="pt_1",
            session_id="sess_pending",
            flow_kind="main_chat",
            status="awaiting_reaction",
            staged_save={"session_id": "sess_pending"},
            original_request={"session_id": "sess_pending"},
            accumulated_reply_text="她已经抬手。",
            accumulated_scene_events=[],
            accumulated_tool_events=[],
            time_spent_min=1,
            pending_reaction=_sample_reaction(),
            continuation_index=0,
            created_at="2026-03-14T00:00:00+00:00",
            updated_at="2026-03-14T00:00:00+00:00",
        )

        save_pending_turn(state)
        loaded = load_pending_turn("sess_pending")

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.pending_turn_id, "pt_1")
        self.assertEqual(loaded.pending_reaction.reaction_id, "react_1")

    def test_cancel_pending_turn_removes_sidecar(self) -> None:
        state = PendingTurnState(
            pending_turn_id="pt_cancel",
            session_id="sess_cancel",
            flow_kind="main_chat",
            status="awaiting_reaction",
            staged_save={"session_id": "sess_cancel"},
            original_request={"session_id": "sess_cancel"},
            accumulated_reply_text="她已经抬手。",
            accumulated_scene_events=[],
            accumulated_tool_events=[],
            time_spent_min=1,
            pending_reaction=_sample_reaction(),
            continuation_index=0,
            created_at="2026-03-14T00:00:00+00:00",
            updated_at="2026-03-14T00:00:00+00:00",
        )
        save_pending_turn(state)

        cancelled = cancel_pending_turn("sess_cancel", "pt_cancel")

        self.assertIsNotNone(cancelled)
        self.assertIsNone(load_pending_turn("sess_cancel"))

    def test_clear_pending_turn_is_noop_when_missing(self) -> None:
        clear_pending_turn("sess_missing")
        self.assertIsNone(load_pending_turn("sess_missing"))


if __name__ == "__main__":
    unittest.main()
