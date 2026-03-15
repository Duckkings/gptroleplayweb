import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.storage import storage_state
from app.models.schemas import ActionCheckResponse, PendingTurnState, Usage
from app.services.pending_turn_service import load_pending_turn
from app.services.reaction_check_service import (
    build_player_reaction_check,
    continue_pending_turn_once,
    stage_reaction_checkpoint,
)
from app.services.world_service import clear_current_save


class ReactionCheckServiceTests(unittest.TestCase):
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

    def test_build_player_reaction_check_validates_required_fields(self) -> None:
        result = build_player_reaction_check(
            {
                "source_kind": "npc_action",
                "source_actor_id": "npc_1",
                "source_actor_name": "醉汉",
                "source_label": "醉汉",
                "trigger_summary": "醉汉抬手朝你打来。",
                "threatened_consequence": "你可能被打中。",
                "ability_used": "dexterity",
                "dc": 12,
                "check_task": "躲开迎面打来的巴掌",
                "success_hint": "你及时偏头躲开。",
                "failure_hint": "你被一巴掌打中。",
            },
            resolution_context="main_chat",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.source_kind, "npc_action")
        self.assertEqual(result.ability_used, "dexterity")
        self.assertEqual(result.dc, 12)

    def test_stage_reaction_checkpoint_persists_pending_turn(self) -> None:
        reaction = build_player_reaction_check(
            {
                "source_kind": "npc_action",
                "source_label": "醉汉",
                "trigger_summary": "醉汉抬手朝你打来。",
                "threatened_consequence": "你可能被打中。",
                "ability_used": "dexterity",
                "dc": 12,
                "check_task": "躲开迎面打来的巴掌",
                "success_hint": "你及时偏头躲开。",
                "failure_hint": "你被一巴掌打中。",
            },
            resolution_context="main_chat",
        )
        assert reaction is not None

        response = stage_reaction_checkpoint(
            session_id="sess_stage",
            flow_kind="main_chat",
            staged_save={"session_id": "sess_stage"},
            original_request={"session_id": "sess_stage"},
            accumulated_reply_text="她已经抬手。",
            accumulated_scene_events=[],
            accumulated_tool_events=[],
            time_spent_min=1,
            pending_reaction=reaction,
            continuation_index=0,
            usage=Usage(input_tokens=1, output_tokens=1),
        )

        self.assertEqual(response.status, "awaiting_reaction")
        self.assertIsNotNone(response.pending_turn_id)
        loaded = load_pending_turn("sess_stage")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.pending_turn_id, response.pending_turn_id)

    def test_continue_pending_turn_once_applies_player_roll(self) -> None:
        session_id = "sess_continue"
        save = clear_current_save(session_id)
        reaction = build_player_reaction_check(
            {
                "source_kind": "npc_action",
                "source_label": "醉汉",
                "trigger_summary": "醉汉抬手朝你打来。",
                "threatened_consequence": "你可能被打中。",
                "ability_used": "dexterity",
                "dc": 12,
                "check_task": "躲开迎面打来的巴掌",
                "success_hint": "你及时偏头躲开。",
                "failure_hint": "你被一巴掌打中。",
            },
            resolution_context="main_chat",
        )
        assert reaction is not None
        state = PendingTurnState(
            pending_turn_id="pt_continue",
            session_id=session_id,
            flow_kind="main_chat",
            status="awaiting_reaction",
            staged_save=save.model_dump(mode="json"),
            original_request={"session_id": session_id},
            accumulated_reply_text="她已经抬手。",
            accumulated_scene_events=[],
            accumulated_tool_events=[],
            time_spent_min=1,
            pending_reaction=reaction,
            continuation_index=0,
            created_at="2026-03-14T00:00:00+00:00",
            updated_at="2026-03-14T00:00:00+00:00",
        )
        result = ActionCheckResponse(
            session_id=session_id,
            actor_role_id=save.player_static_data.player_id,
            actor_name=save.player_static_data.name,
            actor_kind="player",
            action_type="check",
            check_mode="reaction_save",
            requires_check=True,
            ability_used="dexterity",
            ability_modifier=2,
            dc=12,
            check_task="躲开迎面打来的巴掌",
            dice_roll=15,
            total_score=17,
            success=True,
            critical="none",
            time_spent_min=1,
            narrative="因为你豁免成功，你及时偏头躲开。",
            applied_effects=[],
            scene_events=[],
            relation_tag_suggestion=None,
        )

        with patch("app.services.reaction_check_service.world.action_check", return_value=result):
            next_state, action_result = continue_pending_turn_once(state, forced_dice_roll=15, config=None)

        self.assertEqual(action_result.dice_roll, 15)
        self.assertEqual(next_state.time_spent_min, 2)
        self.assertEqual(next_state.staged_save["session_id"], session_id)


if __name__ == "__main__":
    unittest.main()
