import unittest
from pathlib import Path
from shutil import rmtree
from unittest.mock import patch
from uuid import uuid4

from app.core.storage import storage_state
from app.models.schemas import (
    ActionCheckPlanRequest,
    AreaNpc,
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    Coord3D,
    NpcRoleCard,
    PlayerRuntimeData,
    PlayerStaticData,
    Position,
    PublicTurnActionSubmission,
    PublicTurnEntryType,
    PublicTurnPhase,
    PublicTurnPlayerActionCheck,
    TeamMember,
)
from app.services.team_service import ensure_team_state
from app.services.public_turn_runtime import continue_round_in_save, start_round_in_save
from app.services.public_turn_state_store import get_public_turn_state_in_save
from app.services.world_service import clear_current_save, plan_action_check, save_current


class PublicTurnRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        root = Path("backend/.tmp_test") / f"public_turn_runtime_{uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        self._tmpdir = root
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))

    def tearDown(self) -> None:
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        rmtree(self._tmpdir, ignore_errors=True)

    def _seed_public_turn_scene(self, session_id: str):
        save = clear_current_save(session_id)
        save.area_snapshot = AreaSnapshot(
            zones=[AreaZone(zone_id="zone_square", name="Square", center=Coord3D(x=0, y=0, z=0), sub_zone_ids=["sub_square_1"])],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_square_1",
                    zone_id="zone_square",
                    name="Center",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="An open public square.",
                    npcs=[
                        AreaNpc(npc_id="npc_erin", name="艾琳", state="idle"),
                        AreaNpc(npc_id="npc_guard", name="守卫", state="idle"),
                    ],
                )
            ],
            current_zone_id="zone_square",
            current_sub_zone_id="sub_square_1",
            clock=save.area_snapshot.clock,
        )
        position = Position(x=0, y=0, z=0, zone_id="zone_square")
        save.map_snapshot.player_position = position
        save.player_runtime_data = PlayerRuntimeData(session_id=session_id, current_position=position)
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_erin",
                name="艾琳",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                personality="careful",
                speaking_style="direct",
                profile=PlayerStaticData(role_type="npc"),
            ),
            NpcRoleCard(
                role_id="npc_guard",
                name="守卫",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                personality="alert",
                speaking_style="short",
                profile=PlayerStaticData(role_type="npc"),
            ),
            NpcRoleCard(
                role_id="npc_bram",
                name="布莱姆",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                personality="steady",
                speaking_style="low",
                profile=PlayerStaticData(role_type="npc"),
            ),
        ]
        team_state = ensure_team_state(save)
        team_state.members = [
            TeamMember(
                role_id="npc_bram",
                name="布莱姆",
                origin_zone_id="zone_square",
                origin_sub_zone_id="sub_square_1",
                affinity=50,
                trust=40,
            )
        ]
        save_current(save)
        return save

    def test_start_round_next_round_pauses_at_normal_advancement_player_slot(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_next_round")

        result = start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round

        self.assertFalse(result.round_completed)
        self.assertIsNone(result.reaction_check)
        self.assertIsNotNone(round_state)
        assert round_state is not None
        self.assertEqual(round_state.phase, PublicTurnPhase.NORMAL_ADVANCEMENT)
        self.assertTrue(round_state.awaiting_player_action)
        self.assertEqual(round_state.awaiting_player_action_phase, PublicTurnPhase.NORMAL_ADVANCEMENT)
        self.assertEqual(result.presentation.initiative_order, round_state.initiative_order)
        self.assertEqual(result.presentation.round_narration_status, "pending")
        self.assertEqual(result.narration, "")

    def test_start_round_initiative_pauses_at_initiative_player_slot(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_initiative")

        result = start_round_in_save(save, entry_type=PublicTurnEntryType.INITIATIVE, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round

        self.assertFalse(result.round_completed)
        self.assertIsNone(result.reaction_check)
        self.assertIsNotNone(round_state)
        assert round_state is not None
        self.assertEqual(round_state.phase, PublicTurnPhase.INITIATIVE_EXECUTION)
        self.assertTrue(round_state.awaiting_player_action)
        self.assertEqual(round_state.awaiting_player_action_phase, PublicTurnPhase.INITIATIVE_EXECUTION)

    def test_player_submission_writes_relation_team_and_reputation(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_settlement")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)

        with patch("app.services.public_turn_runtime.resolve_ai_round", return_value=([], [], [], None, None)):
            result = continue_round_in_save(
                save,
                submission=PublicTurnActionSubmission(
                    actor_id=save.player_static_data.player_id,
                    action_text="我上前保护艾琳并稳定局面",
                    speech_text="都冷静下来",
                    source_phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
                    forced_first=False,
                ),
                action_check=PublicTurnPlayerActionCheck(
                    action_type="check",
                    source_context="public_turn",
                    resolution_rule="static_dc",
                    planned_requires_check=True,
                    planned_ability_used="wisdom",
                    planned_dc=10,
                    planned_time_spent_min=1,
                    planned_check_task="稳定眼前局势",
                    forced_dice_roll=12,
                ),
                config=None,
            )

        self.assertTrue(result.round_completed)
        self.assertIsNotNone(result.player_action_check_result)
        self.assertGreaterEqual(len(result.impacts), 1)
        impact = result.impacts[0]
        self.assertGreaterEqual(len(impact.relation_deltas), 1)
        self.assertGreaterEqual(len(impact.team_affinity_deltas), 1)
        self.assertEqual(impact.zone_reputation_delta, 1)
        self.assertTrue(any(row.reaction_text for row in impact.relation_deltas))
        self.assertTrue(any(row.reaction_text for row in impact.team_affinity_deltas))
        self.assertGreaterEqual(len(result.presentation.settlement_entries), 1)
        self.assertEqual(result.presentation.settlement_entries[0].actor_id, save.player_static_data.player_id)
        self.assertEqual(result.presentation.round_narration_status, "ready")
        event_kinds = {event.kind for event in result.scene_events}
        self.assertIn("public_turn_relation_update", event_kinds)
        self.assertIn("public_turn_team_update", event_kinds)

    def test_public_turn_plan_action_check_detects_opposed_actor(self) -> None:
        session_id = "sess_public_turn_opposed_plan"
        self._seed_public_turn_scene(session_id)

        result = plan_action_check(
            ActionCheckPlanRequest(
                session_id=session_id,
                action_type="check",
                action_prompt="我抱起艾琳往地上摔",
                actor_role_id="player_001",
                source_context="public_turn",
                config=None,
            )
        )

        self.assertEqual(result.source_context, "public_turn")
        self.assertEqual(result.resolution_rule, "opposed_actor")
        self.assertEqual(result.target_role_id, "npc_erin")
        self.assertEqual(result.target_name, "艾琳")
        self.assertIn(result.target_ability_used, {"strength", "dexterity"})

    def test_public_turn_ai_segment_avoids_extra_embedded_ai_calls(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_segment_batch")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)

        with (
            patch("app.services.world_service._ai_action_plan", side_effect=AssertionError("unexpected _ai_action_plan")),
            patch("app.services.world_service._ai_action_resolution_text", side_effect=AssertionError("unexpected _ai_action_resolution_text")),
            patch("app.services.public_turn_segment_service._planner_overrides", return_value={}) as planner_mock,
            patch(
                "app.services.public_turn_runtime.build_segment_narration_fragments",
                wraps=__import__("app.services.public_turn_runtime", fromlist=["build_segment_narration_fragments"]).build_segment_narration_fragments,
            ) as narrator_mock,
        ):
            result = continue_round_in_save(
                save,
                submission=PublicTurnActionSubmission(
                    actor_id=save.player_static_data.player_id,
                    action_text="我先稳住局势并观察周围 NPC 的反应",
                    speech_text="先别乱动。",
                    source_phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
                    forced_first=False,
                ),
                action_check=PublicTurnPlayerActionCheck(
                    action_type="check",
                    source_context="public_turn",
                    resolution_rule="static_dc",
                    planned_requires_check=True,
                    planned_ability_used="wisdom",
                    planned_dc=10,
                    planned_time_spent_min=1,
                    planned_check_task="稳住眼前局势",
                    forced_dice_roll=12,
                ),
                config=None,
            )

        self.assertTrue(result.round_completed)
        self.assertEqual(planner_mock.call_count, 1)
        self.assertGreaterEqual(narrator_mock.call_count, 1)
        self.assertGreaterEqual(len(result.presentation.settlement_entries), 1)
        self.assertTrue(bool(result.presentation.accumulated_narration.strip()))


if __name__ == "__main__":
    unittest.main()
