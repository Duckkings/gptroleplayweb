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
    EncounterEntry,
    EncounterTemporaryNpc,
    InitiativeDeclaration,
    NpcRoleCard,
    PlayerRuntimeData,
    PlayerStaticData,
    Position,
    PublicTurnActionSubmission,
    PublicTurnActorType,
    PublicTurnEntryType,
    PublicTurnInteractionPrompt,
    PublicTurnInteractionResponseSubmission,
    PublicTurnPhase,
    PublicTurnPlayerActionCheck,
    PublicTurnWorldImpactType,
    TeamMember,
)
from app.services.public_turn_segment_service import plan_public_turn_segment, resolve_public_turn_segment
from app.services.public_turn_narration_formatter import build_settlement_fragment
from app.services.public_turn_interaction_service import InteractionResponseClassification, ResolvedInteractionTarget
from app.services import reaction_check_service
from app.services.team_service import ensure_team_state
from app.services.public_turn_resolution import build_initiative_declarations
from app.services.public_turn_runtime import _resolve_initiative_actor_row, continue_round_in_save, start_round_in_save
from app.services.public_turn_resolution import resolve_ai_actor_turn
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
        self.assertGreaterEqual(len(round_state.initiative_declarations), 2)
        self.assertTrue(any(item.actor_id != save.player_static_data.player_id for item in round_state.initiative_declarations))

    def test_player_submission_writes_relation_team_and_reputation(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_settlement")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)

        with (
            patch("app.services.public_turn_runtime.resolve_ai_round", return_value=([], [], [], None, None)),
            patch("app.services.public_turn_effects._ai_public_turn_npc_reaction", return_value=("皱了皱眉", "先别乱来。")),
            patch("app.services.public_turn_effects._ai_public_turn_team_reaction", return_value=("握紧肩带", "我跟你。", 3, 2)),
        ):
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
        self.assertTrue(any(row.reaction_action == "皱了皱眉" for row in impact.relation_deltas))
        self.assertTrue(any(row.reaction_speech == "先别乱来。" for row in impact.relation_deltas))
        self.assertTrue(any(row.reaction_action == "握紧肩带" for row in impact.team_affinity_deltas))
        self.assertTrue(any(row.reaction_speech == "我跟你。" for row in impact.team_affinity_deltas))
        self.assertGreaterEqual(len(result.presentation.settlement_entries), 1)
        self.assertEqual(result.presentation.settlement_entries[0].actor_id, save.player_static_data.player_id)
        self.assertEqual(result.presentation.round_narration_status, "ready")
        self.assertIn("皱了皱眉", result.narration)
        self.assertIn("我跟你。", result.narration)
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

    def test_player_narration_contains_ai_reactions(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_player_reaction_pause")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        pending_reaction = reaction_check_service.build_player_reaction_check(
            {
                "source_kind": "public_turn",
                "source_actor_id": "npc_guard",
                "source_actor_name": "守卫",
                "source_label": "守卫",
                "trigger_summary": "守卫突然朝你逼近。",
                "threatened_consequence": "你若不及时反应，场面会立刻恶化。",
                "ability_used": "dexterity",
                "dc": 12,
                "check_task": "立刻闪开守卫的压迫动作",
            },
            resolution_context="public_turn",
        )
        assert pending_reaction is not None

        with (
            patch("app.services.public_turn_runtime.resolve_ai_round", return_value=([], [], [], pending_reaction, None)),
            patch("app.services.public_turn_effects._ai_public_turn_npc_reaction", return_value=("压低肩膀", "别把事情闹大。")),
            patch("app.services.public_turn_effects._ai_public_turn_team_reaction", return_value=("侧过半步", "我在这边。", 1, 1)),
        ):
            result = continue_round_in_save(
                save,
                submission=PublicTurnActionSubmission(
                    actor_id=save.player_static_data.player_id,
                    action_text="我抬手示意大家先停下",
                    speech_text="都别冲动。",
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
                    planned_check_task="稳住场面",
                    forced_dice_roll=12,
                ),
                config=None,
            )

        self.assertIn("压低肩膀", result.narration)
        self.assertIn("我在这边。", result.narration)

    def test_public_turn_ai_segment_avoids_extra_embedded_ai_calls(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_segment_batch")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)

        with (
            patch("app.services.world_service._ai_action_plan", side_effect=AssertionError("unexpected _ai_action_plan")),
            patch("app.services.world_service._ai_action_resolution_text", side_effect=AssertionError("unexpected _ai_action_resolution_text")),
            patch("app.services.public_turn_segment_service._planner_overrides", return_value={}) as planner_mock,
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
        self.assertGreaterEqual(len(result.presentation.settlement_entries), 1)
        self.assertTrue(bool(result.presentation.accumulated_narration.strip()))

    def test_public_turn_target_resolution_does_not_lock_player_from_mere_mention(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_target_resolution")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        actor_rows = [
            {
                "actor_id": "npc_guard",
                "name": "守卫",
                "actor_type": "npc",
                "role": next(item for item in save.role_pool if item.role_id == "npc_guard"),
                "priority_reason": "test",
            }
        ]
        with patch(
            "app.services.public_turn_segment_service.public_scene_runtime._ai_actor_action",
            return_value={
                "external_action_narration": "守卫无视玩家的安抚，转身去推开艾琳，把她护到桌边。",
                "speech_line": "你先退后，别挡路。",
                "visible_intent": "先把艾琳从冲突中心推开",
                "specific_threat": "艾琳会被卷进正在扩散的混乱里。",
                "target_label": "艾琳",
                "action_type": "check",
                "action_prompt": "actor=守卫; target=艾琳; intent=推开并护住艾琳",
                "situation_delta_hint": 1,
            },
        ), patch("app.services.public_turn_segment_service._planner_overrides", return_value={}):
            plan = plan_public_turn_segment(
                save,
                round_state=round_state,
                actor_rows=actor_rows,
                phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
                player_text="我试着安抚场面。",
                gm_summary="公开回合继续。",
                audience_context={},
                prior_narration="",
                default_boundary_kind="round_end",
                config=None,
            )
            segment = resolve_public_turn_segment(
                save,
                round_state=round_state,
                actor_lookup={row["actor_id"]: row for row in actor_rows},
                plan=plan,
                context_text="我试着安抚场面。",
                reputation_score=50,
                config=None,
            )

        self.assertIsNone(segment.public_interaction_prompt)
        self.assertIsNone(segment.public_opposed_prompt)
        self.assertGreaterEqual(len(segment.beats), 1)
        self.assertEqual(segment.beats[0].settlement.interaction_target_name, "艾琳")  # type: ignore[union-attr]

    def disabled_public_turn_player_interaction_acceptance_stays_non_opposed(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_interaction_accept")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        round_state.phase = PublicTurnPhase.AWAITING_PLAYER_INTERACTION
        round_state.awaiting_player_action_phase = PublicTurnPhase.NORMAL_ADVANCEMENT
        round_state.pending_interaction_prompt = PublicTurnInteractionPrompt(
            prompt_id="prompt_accept",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
            source_actor_id="npc_bram",
            source_actor_name="布莱姆",
            source_action_type="check",
            source_action_summary="布莱姆伸手扶住你，准备带你离开混乱中心。",
            source_speech_text="先跟我走，别站在中间。",
            source_action_prompt="actor=布莱姆; target=玩家; intent=扶住并带离",
            source_planned_requires_check=True,
            source_planned_ability_used="wisdom",
            source_planned_dc=10,
            source_planned_check_task="把玩家安全带离混乱中心",
            source_interaction_kind="assist",
            target_actor_id=save.player_static_data.player_id,
            target_actor_name=save.player_static_data.name,
            target_actor_kind=PublicTurnActorType.PLAYER,
            stakes_summary="继续停在原地会被卷进冲突。",
            suggested_target_label=save.player_static_data.name,
        )

        result = continue_round_in_save(
            save,
            submission=None,
            interaction_response=PublicTurnInteractionResponseSubmission(
                prompt_id="prompt_accept",
                action_text="我点头，顺着他的力道后撤。",
                speech_text="好，先离开这里。",
            ),
            action_check=None,
            config=None,
        )

        self.assertIsNone(result.public_opposed_prompt)
        self.assertIsNone(result.public_interaction_prompt)
        self.assertGreaterEqual(len(result.settlement_entries), 1)
        self.assertEqual(result.settlement_entries[0].interaction_resolution, "accepted")

    def disabled_public_turn_player_interaction_rejection_escalates_to_opposed(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_interaction_reject")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        round_state.phase = PublicTurnPhase.AWAITING_PLAYER_INTERACTION
        round_state.awaiting_player_action_phase = PublicTurnPhase.NORMAL_ADVANCEMENT
        round_state.pending_interaction_prompt = PublicTurnInteractionPrompt(
            prompt_id="prompt_reject",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
            source_actor_id="npc_guard",
            source_actor_name="守卫",
            source_action_type="check",
            source_action_summary="守卫抓住你的手腕，想把你拖离门口。",
            source_speech_text="你现在必须离开这里。",
            source_action_prompt="actor=守卫; target=玩家; intent=拖走玩家",
            source_planned_requires_check=True,
            source_planned_ability_used="strength",
            source_planned_dc=10,
            source_planned_check_task="把玩家拖离门口",
            source_interaction_kind="move_target",
            target_actor_id=save.player_static_data.player_id,
            target_actor_name=save.player_static_data.name,
            target_actor_kind=PublicTurnActorType.PLAYER,
            stakes_summary="你会被强行拖离当前位置。",
            suggested_target_label=save.player_static_data.name,
        )

        result = continue_round_in_save(
            save,
            submission=None,
            interaction_response=PublicTurnInteractionResponseSubmission(
                prompt_id="prompt_reject",
                action_text="我猛地甩开他的手，死死钉在原地。",
                speech_text="别碰我。",
            ),
            action_check=None,
            config=None,
        )

        self.assertIsNotNone(result.public_opposed_prompt)
        self.assertEqual(result.public_opposed_prompt.target_actor_id, save.player_static_data.player_id)  # type: ignore[union-attr]
        self.assertEqual(result.presentation.phase, PublicTurnPhase.AWAITING_PLAYER_OPPOSED)

    def test_public_turn_player_interaction_acceptance_stays_non_opposed_v2(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_interaction_accept_v2")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        round_state.phase = PublicTurnPhase.AWAITING_PLAYER_INTERACTION
        round_state.awaiting_player_action_phase = PublicTurnPhase.NORMAL_ADVANCEMENT
        round_state.pending_interaction_prompt = PublicTurnInteractionPrompt(
            prompt_id="prompt_accept_v2",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
            source_actor_id="npc_bram",
            source_actor_name="Bram",
            source_action_type="check",
            source_action_summary="Bram greets you and lightly pats your shoulder.",
            source_speech_text="Let's keep moving together.",
            source_action_prompt="actor=Bram; target=player; intent=greet and pat shoulder",
            source_world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
            source_planned_requires_check=False,
            source_interaction_kind="assist",
            target_actor_id=save.player_static_data.player_id,
            target_actor_name=save.player_static_data.name,
            target_actor_kind=PublicTurnActorType.PLAYER,
            suggested_target_label=save.player_static_data.name,
        )

        result = continue_round_in_save(
            save,
            submission=None,
            interaction_response=PublicTurnInteractionResponseSubmission(
                prompt_id="prompt_accept_v2",
                action_text="I nod and move with him.",
                speech_text="Okay, let's go.",
                response_kind="explicit_response",
            ),
            action_check=None,
            config=None,
        )

        self.assertIsNone(result.public_opposed_prompt)
        self.assertIsNone(result.public_interaction_prompt)
        self.assertGreaterEqual(len(result.settlement_entries), 1)
        self.assertIn(result.settlement_entries[0].interaction_resolution, {"accepted", "ambiguous_non_opposed"})
        self.assertEqual(result.settlement_entries[0].interaction_exchange_kind, "non_world_exchange")
        self.assertIsNone(result.settlement_entries[0].check)

    def test_public_turn_player_interaction_rejection_escalates_to_opposed_v2(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_interaction_reject_v2")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        round_state.phase = PublicTurnPhase.AWAITING_PLAYER_INTERACTION
        round_state.awaiting_player_action_phase = PublicTurnPhase.NORMAL_ADVANCEMENT
        round_state.pending_interaction_prompt = PublicTurnInteractionPrompt(
            prompt_id="prompt_reject_v2",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
            source_actor_id="npc_guard",
            source_actor_name="Guard",
            source_action_type="check",
            source_action_summary="The guard grabs your arm and tries to drag you away from the doorway.",
            source_speech_text="You leave now.",
            source_action_prompt="actor=guard; target=player; intent=drag player away",
            source_world_impact_type=PublicTurnWorldImpactType.WORLD,
            source_planned_requires_check=True,
            source_planned_ability_used="strength",
            source_planned_dc=10,
            source_planned_check_task="Drag the player away from the doorway",
            source_interaction_kind="move_target",
            target_actor_id=save.player_static_data.player_id,
            target_actor_name=save.player_static_data.name,
            target_actor_kind=PublicTurnActorType.PLAYER,
            suggested_target_label=save.player_static_data.name,
        )

        result = continue_round_in_save(
            save,
            submission=None,
            interaction_response=PublicTurnInteractionResponseSubmission(
                prompt_id="prompt_reject_v2",
                action_text="I wrench my arm free and brace in place.",
                speech_text="Don't touch me.",
            ),
            action_check=None,
            config=None,
        )

        self.assertIsNotNone(result.public_opposed_prompt)
        self.assertEqual(result.public_opposed_prompt.target_actor_id, save.player_static_data.player_id)  # type: ignore[union-attr]
        self.assertEqual(result.presentation.phase, PublicTurnPhase.AWAITING_PLAYER_OPPOSED)

    def test_public_turn_player_interaction_no_action_keeps_round_moving(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_interaction_no_action")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        round_state.phase = PublicTurnPhase.AWAITING_PLAYER_INTERACTION
        round_state.awaiting_player_action_phase = PublicTurnPhase.NORMAL_ADVANCEMENT
        round_state.pending_interaction_prompt = PublicTurnInteractionPrompt(
            prompt_id="prompt_no_action",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
            source_actor_id="npc_bram",
            source_actor_name="Bram",
            source_action_type="check",
            source_action_summary="Bram offers a quick greeting and taps your shoulder.",
            source_speech_text="Stay sharp.",
            source_action_prompt="actor=Bram; target=player; intent=greeting",
            source_world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
            source_planned_requires_check=False,
            source_interaction_kind="assist",
            target_actor_id=save.player_static_data.player_id,
            target_actor_name=save.player_static_data.name,
            target_actor_kind=PublicTurnActorType.PLAYER,
            suggested_target_label=save.player_static_data.name,
        )

        result = continue_round_in_save(
            save,
            submission=None,
            interaction_response=PublicTurnInteractionResponseSubmission(
                prompt_id="prompt_no_action",
                action_text="",
                speech_text="",
                response_kind="no_action",
            ),
            action_check=None,
            config=None,
        )

        self.assertIsNone(result.public_interaction_prompt)
        self.assertIsNone(result.public_opposed_prompt)
        self.assertGreaterEqual(len(result.settlement_entries), 1)
        self.assertEqual(result.settlement_entries[0].target_response_kind, "no_action")
        self.assertEqual(result.settlement_entries[0].interaction_exchange_kind, "non_world_exchange")
        current_round = get_public_turn_state_in_save(save).current_round
        assert current_round is not None
        self.assertIsNone(current_round.pending_interaction_prompt)

    def test_public_turn_invalid_alternation_target_keeps_pending_prompt(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_interaction_invalid_reverse")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        round_state.phase = PublicTurnPhase.AWAITING_PLAYER_INTERACTION
        round_state.awaiting_player_action_phase = PublicTurnPhase.NORMAL_ADVANCEMENT
        round_state.pending_interaction_prompt = PublicTurnInteractionPrompt(
            prompt_id="prompt_invalid_reverse",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
            source_actor_id="npc_bram",
            source_actor_name="Bram",
            source_action_type="check",
            source_action_summary="Bram greets you and taps your shoulder.",
            source_speech_text="Good to see you.",
            source_action_prompt="actor=Bram; target=player; intent=greeting",
            source_world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
            source_planned_requires_check=False,
            source_interaction_kind="assist",
            target_actor_id=save.player_static_data.player_id,
            target_actor_name=save.player_static_data.name,
            target_actor_kind=PublicTurnActorType.PLAYER,
            suggested_target_label=save.player_static_data.name,
        )

        with (
            patch(
                "app.services.public_turn_resolution.classify_player_interaction_response",
                return_value=InteractionResponseClassification(
                    action_text="I slap the guard instead.",
                    speech_text="Back off.",
                    speech_target_label="guard",
                    target_label="guard",
                    world_impact_type=PublicTurnWorldImpactType.WORLD,
                ),
            ),
            patch(
                "app.services.public_turn_resolution.resolve_interaction_target",
                return_value=ResolvedInteractionTarget(
                    actor_id="npc_guard",
                    name="Guard",
                    actor_kind="npc",
                    actor_type=PublicTurnActorType.NPC,
                ),
            ),
            self.assertRaisesRegex(ValueError, "PUBLIC_TURN_ALTERNATION_TARGET_MISMATCH"),
        ):
            continue_round_in_save(
                save,
                submission=None,
                interaction_response=PublicTurnInteractionResponseSubmission(
                    prompt_id="prompt_invalid_reverse",
                    action_text="I slap the guard instead.",
                    speech_text="Back off.",
                ),
                action_check=None,
                config=None,
            )

        state_after = get_public_turn_state_in_save(save)
        assert state_after.current_round is not None
        self.assertEqual(state_after.current_round.phase, PublicTurnPhase.AWAITING_PLAYER_INTERACTION)
        self.assertIsNotNone(state_after.current_round.pending_interaction_prompt)

    def test_player_targeted_attack_routes_to_interaction_not_reaction(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_player_targeted_attack")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        actor_rows = [
            {
                "actor_id": "npc_guard",
                "name": "守卫",
                "actor_type": "npc",
                "role": next(item for item in save.role_pool if item.role_id == "npc_guard"),
                "priority_reason": "test",
            }
        ]
        with patch(
            "app.services.public_turn_segment_service.public_scene_runtime._ai_actor_action",
            return_value={
                "external_action_narration": "守卫猛地伸手压向玩家的肩膀，想把人按回原地。",
                "speech_line": "商队领队，先退后！",
                "visible_intent": "先把玩家按住，别让局面继续扩散",
                "specific_threat": "如果玩家继续顶上去，冲突会立刻升级。",
                "target_label": save.player_static_data.name,
                "speech_target_label": "商队领队",
                "action_type": "attack",
                "action_prompt": f"actor=守卫; target={save.player_static_data.name}; intent=按住玩家",
                "situation_delta_hint": 2,
            },
        ), patch("app.services.public_turn_segment_service._planner_overrides", return_value={}):
            plan = plan_public_turn_segment(
                save,
                round_state=round_state,
                actor_rows=actor_rows,
                phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
                player_text="我上前拦住他",
                gm_summary="公开回合继续",
                audience_context={},
                prior_narration="",
                default_boundary_kind="round_end",
                config=None,
            )
            segment = resolve_public_turn_segment(
                save,
                round_state=round_state,
                actor_lookup={row["actor_id"]: row for row in actor_rows},
                plan=plan,
                context_text="我上前拦住他",
                reputation_score=50,
                config=None,
            )

        self.assertIsNotNone(segment.public_interaction_prompt)
        self.assertIsNone(segment.pending_reaction)
        prompt = segment.public_interaction_prompt
        assert prompt is not None
        self.assertEqual(prompt.source_action_target_name, save.player_static_data.name)
        self.assertEqual(prompt.source_speech_target_name, "商队领队")

    def test_settlement_narration_uses_speech_target_name(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_speech_target_narration")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        actor = {
            "actor_id": "npc_guard",
            "name": "守卫",
            "actor_type": "npc",
            "priority_reason": "test",
            "role": next(item for item in save.role_pool if item.role_id == "npc_guard"),
        }
        with (
            patch(
                "app.services.public_turn_resolution.public_scene_runtime._ai_actor_action",
                return_value={
                    "external_action_narration": "伸手压向玩家的肩膀",
                    "speech_line": "老东西，退后！",
                    "visible_intent": "把玩家按住",
                    "specific_threat": "场面会继续恶化",
                    "target_label": save.player_static_data.name,
                    "speech_target_label": "艾琳",
                    "action_type": "attack",
                    "action_prompt": f"actor=守卫; target={save.player_static_data.name}; intent=按住玩家",
                    "situation_delta_hint": 2,
                },
            ),
            patch("app.services.public_turn_resolution.public_scene_runtime.should_force_public_action_check", return_value=False),
        ):
            _, impact, settlement, _, _ = resolve_ai_actor_turn(
                save,
                actor=actor,
                player_text="我上前拦住他",
                gm_summary="公开回合继续",
                round_state=round_state,
                scene_context={},
                audience_context={},
                reputation_score=50,
                config=None,
            )

        assert impact is not None
        assert settlement is not None
        settlement.action_target_name = save.player_static_data.name
        settlement.speech_target_name = "艾琳"
        narration = build_settlement_fragment(settlement)
        self.assertIn("朝艾琳说", narration)

    def test_warning_reaction_clamps_positive_relation_delta(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_warning_clamp")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)

        with (
            patch("app.services.public_turn_runtime.resolve_ai_round", return_value=([], [], [], None, None)),
            patch(
                "app.services.public_turn_effects._ai_public_turn_npc_reaction",
                return_value=("按住短剑柄", "别再往前了。", "warning", "守卫", save.player_static_data.name, "current_conflict"),
            ),
            patch(
                "app.services.public_turn_effects._ai_public_turn_team_reaction",
                return_value=("抿紧嘴角", "我跟上你。", 1, 1, "supportive", "守卫", save.player_static_data.name, "current_conflict"),
            ),
        ):
            result = continue_round_in_save(
                save,
                submission=PublicTurnActionSubmission(
                    actor_id=save.player_static_data.player_id,
                    action_text="我一拳打向守卫的下巴",
                    speech_text="住手。",
                    source_phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
                    forced_first=False,
                ),
                action_check=PublicTurnPlayerActionCheck(
                    action_type="check",
                    source_context="public_turn",
                    resolution_rule="static_dc",
                    planned_requires_check=True,
                    planned_ability_used="strength",
                    planned_dc=10,
                    planned_time_spent_min=1,
                    planned_check_task="压住守卫",
                    forced_dice_roll=19,
                ),
                config=None,
            )

        npc_row = result.impacts[0].relation_deltas[0]
        self.assertEqual(npc_row.reaction_tone, "warning")
        self.assertLessEqual(npc_row.relation_delta, 0)

    def test_invalid_reaction_tone_is_sanitized_before_validation(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_invalid_reaction_tone")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)

        with (
            patch("app.services.public_turn_runtime.resolve_ai_round", return_value=([], [], [], None, None)),
            patch(
                "app.services.public_turn_effects._ai_public_turn_npc_reaction",
                return_value=("narrows his eyes", "Stop there.", "??invalid??", "Guard", save.player_static_data.name, "current_conflict"),
            ),
            patch(
                "app.services.public_turn_effects._ai_public_turn_team_reaction",
                return_value=("takes a breath", "Easy.", 1, 1, "oops", "Guard", save.player_static_data.name, "current_conflict"),
            ),
        ):
            result = continue_round_in_save(
                save,
                submission=PublicTurnActionSubmission(
                    actor_id=save.player_static_data.player_id,
                    action_text="I step between the guard and the crowd.",
                    speech_text="Everyone back off.",
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
                    planned_check_task="steady the crowd",
                    forced_dice_roll=14,
                ),
                config=None,
            )

        impact = result.impacts[0]
        self.assertIn(impact.relation_deltas[0].reaction_tone, {"neutral", "concerned", "warning", "hostile", "supportive", "approving"})
        self.assertIn(impact.team_affinity_deltas[0].reaction_tone, {"neutral", "concerned", "warning", "hostile", "supportive", "approving"})

    def test_build_initiative_declarations_accepts_encounter_temp_npc(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_temp_npc_declaration")

        with patch(
            "app.services.public_turn_resolution.initiative_actor_rows",
            return_value=[
                {
                    "actor_id": "encnpc_1",
                    "name": "Watcher",
                    "actor_type": "encounter_temp_npc",
                }
            ],
        ):
            declarations = build_initiative_declarations(
                save,
                player_action_text="I attack the source of the threat.",
                config=None,
            )

        self.assertEqual(len(declarations), 1)
        self.assertEqual(declarations[0].actor_id, "encnpc_1")
        self.assertEqual(declarations[0].actor_type, "encounter_temp_npc")

    def test_resolve_initiative_actor_row_preserves_encounter_temp_npc(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_temp_npc_row")
        save.encounter_state.encounters = [
            EncounterEntry(
                encounter_id="enc_public_turn",
                type="event",
                status="active",
                title="Tavern Clash",
                description="A fast public encounter.",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                temporary_npcs=[
                    EncounterTemporaryNpc(
                        encounter_npc_id="encnpc_1",
                        name="Watcher",
                        title="Watcher",
                        description="Keeps an eye on the crowd.",
                        speaking_style="brief",
                        agenda="contain the fight",
                        zone_id="zone_square",
                        sub_zone_id="sub_square_1",
                    )
                ],
            )
        ]
        save.encounter_state.active_encounter_id = "enc_public_turn"

        row = _resolve_initiative_actor_row(
            save,
            declaration=InitiativeDeclaration(
                actor_id="encnpc_1",
                actor_type="encounter_temp_npc",
                actor_name="Watcher",
                declared_action="Cuts in to contain the threat.",
            ),
            context_text="player prepares to act first",
            config=None,
        )

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.get("actor_type"), "encounter_temp_npc")
        self.assertEqual(row.get("actor_id"), "encnpc_1")
        self.assertIsNotNone(row.get("temp_npc"))

    def test_priority_action_declarations_are_not_player_only(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_priority_mix")

        declarations = build_initiative_declarations(
            save,
            player_action_text="player prepares to act first",
            mode="priority_action",
            config=None,
        )

        self.assertGreaterEqual(len(declarations), 1)
        self.assertTrue(any(item.actor_id != save.player_static_data.player_id for item in declarations))

    def test_npc_actor_turn_has_no_attitude_consequences_or_reputation(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_npc_consequence_scope")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        actor = {
            "actor_id": "npc_guard",
            "name": "守卫",
            "actor_type": "npc",
            "priority_reason": "test",
            "role": next(item for item in save.role_pool if item.role_id == "npc_guard"),
        }

        with (
            patch(
                "app.services.public_turn_resolution.public_scene_runtime._ai_actor_action",
                return_value={
                    "external_action_narration": "守卫上前一步压住人群边线。",
                    "speech_line": "往后退。",
                    "visible_intent": "稳住局面",
                    "specific_threat": "混乱会继续扩散。",
                    "target_label": "",
                    "action_type": "check",
                    "action_prompt": "守卫稳住局面",
                    "situation_delta_hint": 4,
                },
            ),
            patch("app.services.public_turn_resolution.public_scene_runtime.should_force_public_action_check", return_value=False),
        ):
            _, impact, settlement, _, _ = resolve_ai_actor_turn(
                save,
                actor=actor,
                player_text="玩家刚刚停手。",
                gm_summary="公开回合继续。",
                round_state=round_state,
                scene_context={},
                audience_context={},
                reputation_score=50,
                config=None,
            )

        assert impact is not None
        assert settlement is not None
        self.assertEqual(impact.zone_reputation_delta, 0)
        self.assertEqual(impact.relation_deltas, [])
        self.assertEqual(impact.team_affinity_deltas, [])
        self.assertEqual(settlement.zone_reputation_delta, 0)
        self.assertEqual(settlement.relation_deltas, [])
        self.assertEqual(settlement.team_affinity_deltas, [])

    def test_team_actor_turn_can_change_reputation_without_self_reaction(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_team_reputation_scope")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        actor = {
            "actor_id": "npc_bram",
            "name": "布莱姆",
            "actor_type": "team",
            "priority_reason": "test",
            "role": next(item for item in save.role_pool if item.role_id == "npc_bram"),
        }

        with (
            patch(
                "app.services.public_turn_resolution.public_scene_runtime._ai_actor_action",
                return_value={
                    "external_action_narration": "布莱姆站到玩家身旁，先稳住围观人群。",
                    "speech_line": "先别乱。",
                    "visible_intent": "为玩家阵营争取喘息",
                    "specific_threat": "围观者的惊慌还在蔓延。",
                    "target_label": "",
                    "action_type": "check",
                    "action_prompt": "布莱姆稳住人群",
                    "situation_delta_hint": 4,
                },
            ),
            patch("app.services.public_turn_resolution.public_scene_runtime.should_force_public_action_check", return_value=False),
        ):
            _, impact, settlement, _, _ = resolve_ai_actor_turn(
                save,
                actor=actor,
                player_text="玩家刚刚停手。",
                gm_summary="公开回合继续。",
                round_state=round_state,
                scene_context={},
                audience_context={},
                reputation_score=50,
                config=None,
            )

        assert impact is not None
        assert settlement is not None
        self.assertEqual(impact.zone_reputation_delta, 1)
        self.assertEqual(impact.relation_deltas, [])
        self.assertEqual(impact.team_affinity_deltas, [])
        self.assertEqual(settlement.zone_reputation_delta, 1)
        self.assertEqual(settlement.team_affinity_deltas, [])

    def test_player_settlement_omits_gm_resolution_summary(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_no_actor_gm_summary")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)

        with patch("app.services.public_turn_runtime.resolve_ai_round", return_value=([], [], [], None, None)):
            result = continue_round_in_save(
                save,
                submission=PublicTurnActionSubmission(
                    actor_id=save.player_static_data.player_id,
                    action_text="steady the situation",
                    speech_text="Hold.",
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
                    planned_check_task="steady the situation",
                    forced_dice_roll=12,
                ),
                config=None,
            )

        self.assertEqual(result.presentation.settlement_entries[0].gm_resolution_summary, "")

    def test_gm_push_sets_roll_result_on_final_settlement(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_gm_push_result")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)

        with (
            patch("app.services.public_turn_runtime.resolve_ai_round", return_value=([], [], [], None, None)),
            patch("app.services.public_turn_gm_push_service.random.randint", return_value=5),
        ):
            result = continue_round_in_save(
                save,
                submission=PublicTurnActionSubmission(
                    actor_id=save.player_static_data.player_id,
                    action_text="watch the room",
                    speech_text="Stay sharp.",
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
                    planned_check_task="watch the room",
                    forced_dice_roll=10,
                ),
                config=None,
            )

        self.assertTrue(result.round_completed)
        gm_entry = result.presentation.settlement_entries[-1]
        self.assertEqual(gm_entry.entry_kind, "gm_push")
        self.assertIsNotNone(gm_entry.gm_push_result)
        self.assertEqual(gm_entry.gm_push_result.roll_d6, 5)  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
