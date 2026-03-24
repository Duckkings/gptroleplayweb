import unittest
from pathlib import Path
from pydantic import ValidationError
from shutil import rmtree
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app.core.storage import storage_state
from app.models.schemas import (
    ActionCheckRequest,
    ActionCheckResponse,
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
    PublicTurnOpposedPlanResponse,
    PublicTurnOpposedPrompt,
    PublicTurnPhase,
    PublicTurnPlayerActionCheck,
    PublicTurnRound,
    PublicTurnSegmentActorDirective,
    PublicTurnSegmentBoundary,
    PublicTurnSegmentPlan,
    PublicTurnSettlementCheck,
    PublicTurnSettlementEntry,
    PublicTurnWorldImpactType,
    ChatConfig,
    TeamMember,
)
from app.services.public_turn_attack_service import PublicTurnResolvedAttackTarget, assess_public_turn_attack, classify_attack_response, resolve_attack_definition
from app.services.public_turn_candidates import initiative_actor_rows
from app.services.public_turn_segment_service import plan_public_turn_segment, resolve_public_turn_segment
from app.services.public_turn_narration_formatter import build_settlement_fragment
from app.services.public_turn_interaction_service import InteractionResponseClassification, ResolvedInteractionTarget
from app.services import reaction_check_service
from app.services.team_service import ensure_team_state
from app.services.public_turn_resolution import (
    _apply_public_turn_hp_damage,
    _build_attack_resolution_bundle,
    _extract_resolution_summary_text,
    build_initiative_declarations,
    prepare_npc_attack_prompt,
    resolve_player_attack_submission,
    resolve_player_submission,
)
from app.services.public_turn_runtime import (
    _resolve_initiative_actor_row,
    continue_round_in_save,
    resume_round_after_opposed_in_save,
    start_round_in_save,
)
from app.services.public_turn_resolution import resolve_ai_actor_turn, resolve_opposed_prompt_submission
from app.services.public_turn_state_store import get_public_turn_state_in_save, save_public_turn_state_in_save
from app.services.world_service import _visible_public_roles, action_check, clear_current_save, plan_action_check, save_current


def _fake_completion_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


class _FakeSyncClient:
    def __init__(self, content: str) -> None:
        self._response = _fake_completion_response(content)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_: object) -> SimpleNamespace:
        return self._response


class PublicTurnRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        root = Path("backend/.tmp_test") / f"public_turn_runtime_{uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        self._tmpdir = root
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))
        self._patchers = [
            patch("app.services.public_turn_effects._ai_public_turn_npc_reaction", side_effect=self._fake_npc_reaction),
            patch("app.services.public_turn_effects._ai_public_turn_team_reaction", side_effect=self._fake_team_reaction),
            patch("app.services.public_scene_runtime_v2._ai_actor_action", side_effect=self._fake_actor_action),
            patch("app.services.public_turn_segment_service._planner_overrides", return_value={}),
            patch("app.services.world_service._ai_action_plan", side_effect=self._fake_action_plan),
            patch(
                "app.services.public_turn_interaction_service.classify_player_interaction_response",
                side_effect=self._fake_interaction_response,
            ),
            patch(
                "app.services.public_turn_resolution.classify_player_interaction_response",
                side_effect=self._fake_interaction_response,
            ),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(getattr(self, "_patchers", [])):
            patcher.stop()
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        rmtree(self._tmpdir, ignore_errors=True)

    def _fake_npc_reaction(self, *args, **kwargs):
        return ("皱了皱眉", "", "neutral", "", "", "single")

    def _fake_team_reaction(self, *args, **kwargs):
        return ("点了点头", "", 0, 0, "neutral", "", "", "single")

    def _fake_actor_action(self, save, actor, *args, **kwargs):
        actor_name = str(actor.get("name") or "Actor")
        return {
            "response_mode": "respond",
            "action_type": "check",
            "world_impact_type": "non_world",
            "visible_intent": f"{actor_name} keeps watch.",
            "external_action_narration": f"{actor_name} keeps watch.",
            "speech_line": "",
            "specific_threat": "",
            "action_prompt": f"actor={actor_name}; intent=keep watch",
            "target_label": "",
            "speech_target_label": "",
        }

    def _fake_action_plan(self, *args, **kwargs):
        return {
            "ability_used": "wisdom",
            "dc": 12,
            "time_spent_min": 1,
            "requires_check": True,
            "check_task": "test task",
        }

    def _fake_interaction_response(self, *args, **kwargs):
        action_text = str(kwargs.get("action_text") or "")
        speech_text = str(kwargs.get("speech_text") or "")
        source_actor_name = str(kwargs.get("source_actor_name") or "")
        combined = f"{action_text}\n{speech_text}".lower()
        is_world = any(token in combined for token in ("wrench", "free", "brace", "don't touch", "推开", "挣脱", "别碰我", "反抗"))
        return InteractionResponseClassification(
            action_text=action_text,
            speech_text=speech_text,
            speech_target_label=None,
            target_label=(source_actor_name if action_text.strip() else None),
            world_impact_type=(PublicTurnWorldImpactType.WORLD if is_world else PublicTurnWorldImpactType.NON_WORLD),
            consent_state=("rejected" if is_world else "accepted"),
            contest_state=("opposed" if is_world else "non_opposed"),
        )

    @staticmethod
    def _ai_config() -> ChatConfig:
        return ChatConfig(
            provider="openai",
            api_key="test-key",
            model="gpt-4o-mini",
            stream=False,
            gm_prompt="You are a GM.",
        )

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
            patch(
                "app.services.public_turn_effects._ai_public_turn_npc_reaction",
                return_value=("皱了皱眉", "先别乱来。", "neutral", "", "", "single"),
            ),
            patch(
                "app.services.public_turn_effects._ai_public_turn_team_reaction",
                return_value=("握紧肩带", "我跟你。", 3, 2, "supportive", "", "", "single"),
            ),
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
        impact = next(item for item in result.impacts if item.actor_id == save.player_static_data.player_id)
        self.assertGreaterEqual(len(impact.relation_deltas), 1)
        self.assertGreaterEqual(len(impact.team_affinity_deltas), 1)
        self.assertGreaterEqual(impact.zone_reputation_delta, 0)
        self.assertTrue(any(row.reaction_action == "皱了皱眉" for row in impact.relation_deltas))
        self.assertTrue(any(row.reaction_speech == "先别乱来。" for row in impact.relation_deltas))
        self.assertTrue(any(row.reaction_action == "握紧肩带" for row in impact.team_affinity_deltas))
        self.assertTrue(any(row.reaction_speech == "我跟你。" for row in impact.team_affinity_deltas))
        self.assertGreaterEqual(len(result.presentation.settlement_entries), 1)
        player_entry = next(item for item in result.presentation.settlement_entries if item.actor_id == save.player_static_data.player_id)
        self.assertEqual(player_entry.actor_id, save.player_static_data.player_id)
        self.assertEqual(player_entry.zone_reputation_delta, impact.zone_reputation_delta)
        self.assertEqual(result.presentation.round_narration_status, "ready")
        self.assertIn("皱了皱眉", result.narration)
        self.assertIn("我跟你。", result.narration)
        event_kinds = {event.kind for event in result.scene_events}
        self.assertIn("public_turn_relation_update", event_kinds)
        self.assertIn("public_turn_team_update", event_kinds)

    def test_public_turn_team_reaction_keeps_ai_delta_magnitude(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_team_delta")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)

        with (
            patch("app.services.public_turn_runtime.resolve_ai_round", return_value=([], [], [], None, None)),
            patch(
                "app.services.public_turn_effects._ai_public_turn_npc_reaction",
                return_value=("皱了皱眉", "先别乱来。", "neutral", "", "", "single"),
            ),
            patch(
                "app.services.public_turn_effects._ai_public_turn_team_reaction",
                return_value=("握紧肩带", "我跟你。", 8, 7, "supportive", "", "", "single"),
            ),
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

        impact = next(item for item in result.impacts if item.actor_id == save.player_static_data.player_id)
        self.assertTrue(any(row.affinity_delta == 8 for row in impact.team_affinity_deltas))
        self.assertTrue(any(row.trust_delta == 7 for row in impact.team_affinity_deltas))
        self.assertGreaterEqual(len(result.presentation.settlement_entries), 1)

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
            patch(
                "app.services.public_turn_effects._ai_public_turn_npc_reaction",
                return_value=("压低肩膀", "别把事情闹大。", "neutral", "", "", "single"),
            ),
            patch(
                "app.services.public_turn_effects._ai_public_turn_team_reaction",
                return_value=("侧过半步", "我在这边。", 1, 1, "supportive", "", "", "single"),
            ),
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

    def test_public_turn_prompt_keeps_object_action_target_when_player_is_only_speech_target(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_prompt_object_target")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        actor_rows = [
            {
                "actor_id": "npc_guard",
                "name": "Guard",
                "actor_type": "npc",
                "role": next(item for item in save.role_pool if item.role_id == "npc_guard"),
                "priority_reason": "test",
            }
        ]
        with patch(
            "app.services.public_turn_segment_service.public_scene_runtime._ai_actor_action",
            return_value={
                "external_action_narration": "Guard jumps onto the desk and steadies the smoking relay core.",
                "speech_line": "Stay back and don't touch it.",
                "visible_intent": "Guard stabilizes the smoking relay core.",
                "specific_threat": "The relay core could rupture if anyone interferes.",
                "target_label": "smoking relay core",
                "speech_target_label": save.player_static_data.name,
                "action_type": "check",
                "action_prompt": "actor=Guard; intent=stabilize the smoking relay core while warning the player",
                "situation_delta_hint": 1,
            },
        ), patch("app.services.public_turn_segment_service._planner_overrides", return_value={}):
            plan = plan_public_turn_segment(
                save,
                round_state=round_state,
                actor_rows=actor_rows,
                phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
                player_text="I watch the guard handle the device.",
                gm_summary="The relay core is spitting sparks across the desk.",
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
                context_text="I watch the guard handle the device.",
                reputation_score=50,
                config=None,
            )

        self.assertIsNotNone(segment.public_interaction_prompt)
        self.assertIsNone(segment.public_opposed_prompt)
        prompt = segment.public_interaction_prompt
        assert prompt is not None
        self.assertEqual(prompt.target_actor_id, save.player_static_data.player_id)
        self.assertEqual(prompt.target_actor_name, save.player_static_data.name)
        self.assertEqual(prompt.source_action_target_name, "smoking relay core")
        self.assertEqual(prompt.source_speech_target_name, save.player_static_data.name)

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

    def test_public_turn_player_interaction_direct_attack_against_actor_escalates_to_opposed(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_interaction_direct_attack_v2")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        round_state.phase = PublicTurnPhase.AWAITING_PLAYER_INTERACTION
        round_state.awaiting_player_action_phase = PublicTurnPhase.INITIATIVE_EXECUTION
        round_state.pending_interaction_prompt = PublicTurnInteractionPrompt(
            prompt_id="prompt_direct_attack_v2",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.INITIATIVE_EXECUTION,
            source_actor_id="npc_guard",
            source_actor_name="Guard",
            source_action_type="check",
            source_action_summary="The guard sweeps the lantern off the desk and lunges to seize the ledger before you can react.",
            source_speech_text="Try me.",
            source_action_prompt="actor=guard; target=player; intent=seize the ledger under threat",
            source_world_impact_type=PublicTurnWorldImpactType.WORLD,
            source_planned_requires_check=True,
            source_planned_ability_used="wisdom",
            source_planned_dc=12,
            source_planned_check_task="Force control of the ledger",
            source_interaction_kind="targeted_interaction",
            target_actor_id=save.player_static_data.player_id,
            target_actor_name=save.player_static_data.name,
            target_actor_kind=PublicTurnActorType.PLAYER,
            suggested_target_label=save.player_static_data.name,
        )

        with patch(
            "app.services.public_turn_resolution.classify_player_interaction_response",
            return_value=InteractionResponseClassification(
                action_text="I keep firing magic missiles at him.",
                speech_text="Die.",
                speech_target_label=None,
                target_label="Guard",
                world_impact_type=PublicTurnWorldImpactType.WORLD,
            ),
        ):
            result = continue_round_in_save(
                save,
                submission=None,
                interaction_response=PublicTurnInteractionResponseSubmission(
                    prompt_id="prompt_direct_attack_v2",
                    action_text="I keep firing magic missiles at him.",
                    speech_text="Die.",
                    response_kind="explicit_response",
                ),
                action_check=None,
                config=None,
            )

        self.assertIsNotNone(result.public_opposed_prompt)
        self.assertEqual(result.public_opposed_prompt.source_actor_id, "npc_guard")  # type: ignore[union-attr]
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

    def test_public_turn_interaction_submission_preserves_non_player_action_target(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_interaction_object_target")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        round_state.phase = PublicTurnPhase.AWAITING_PLAYER_INTERACTION
        round_state.awaiting_player_action_phase = PublicTurnPhase.NORMAL_ADVANCEMENT
        round_state.pending_interaction_prompt = PublicTurnInteractionPrompt(
            prompt_id="prompt_object_target",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
            source_actor_id="npc_guard",
            source_actor_name="Guard",
            source_action_type="check",
            source_action_summary="Guard braces over the smoking relay core and tightens the loose housing.",
            source_speech_text="Stay back.",
            source_action_target_name="smoking relay core",
            source_speech_target_name=save.player_static_data.name,
            source_action_prompt="actor=Guard; intent=stabilize the smoking relay core while warning the player",
            source_world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
            source_planned_requires_check=False,
            source_interaction_kind="targeted_interaction",
            target_actor_id=save.player_static_data.player_id,
            target_actor_name=save.player_static_data.name,
            target_actor_kind=PublicTurnActorType.PLAYER,
            suggested_target_label=save.player_static_data.name,
        )

        result = continue_round_in_save(
            save,
            submission=None,
            interaction_response=PublicTurnInteractionResponseSubmission(
                prompt_id="prompt_object_target",
                action_text="",
                speech_text="",
                response_kind="no_action",
            ),
            action_check=None,
            config=None,
        )

        self.assertGreaterEqual(len(result.settlement_entries), 1)
        settlement = result.settlement_entries[0]
        self.assertEqual(settlement.action_target_name, "smoking relay core")
        self.assertIsNone(settlement.action_target_actor_id)
        self.assertEqual(settlement.interaction_target_name, save.player_static_data.name)
        self.assertEqual(settlement.target_response_kind, "no_action")

    def test_public_turn_interaction_no_action_pauses_for_player_initiative_slot_when_player_is_next(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_interaction_no_action_player_next")
        state = get_public_turn_state_in_save(save)
        round_state = PublicTurnRound(
            round_id="ptround_player_next",
            round_number=1,
            phase=PublicTurnPhase.AWAITING_PLAYER_INTERACTION,
            initiative_declarations=[
                InitiativeDeclaration(
                    actor_id="npc_guard",
                    actor_name="Guard",
                    actor_type="npc",
                    declared_action="Guard cuts in first.",
                    dex_modifier=1,
                    roll_d20=20,
                    total_initiative=21,
                ),
                InitiativeDeclaration(
                    actor_id=save.player_static_data.player_id,
                    actor_name=save.player_static_data.name,
                    actor_type="player",
                    declared_action="Take initiative",
                    dex_modifier=0,
                    roll_d20=19,
                    total_initiative=19,
                ),
                InitiativeDeclaration(
                    actor_id="npc_bram",
                    actor_name="Bram",
                    actor_type="team",
                    declared_action="Bram covers the player.",
                    dex_modifier=3,
                    roll_d20=13,
                    total_initiative=16,
                ),
            ],
            awaiting_player_action_phase=PublicTurnPhase.INITIATIVE_EXECUTION,
            pending_interaction_prompt=PublicTurnInteractionPrompt(
                prompt_id="prompt_no_action_player_next",
                round_id="ptround_player_next",
                phase=PublicTurnPhase.INITIATIVE_EXECUTION,
                source_actor_id="npc_guard",
                source_actor_name="Guard",
                source_action_type="check",
                source_action_summary="Guard blocks your path and orders you to stay put.",
                source_speech_text="Don't move.",
                source_action_prompt="actor=Guard; target=player; intent=block player",
                source_world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
                source_planned_requires_check=False,
                source_interaction_kind="block",
                target_actor_id=save.player_static_data.player_id,
                target_actor_name=save.player_static_data.name,
                target_actor_kind=PublicTurnActorType.PLAYER,
                suggested_target_label=save.player_static_data.name,
            ),
        )
        state.current_round = round_state
        state.awaiting_player_entry = False
        save_public_turn_state_in_save(save, state)

        result = continue_round_in_save(
            save,
            submission=None,
            interaction_response=PublicTurnInteractionResponseSubmission(
                prompt_id="prompt_no_action_player_next",
                action_text="",
                speech_text="",
                response_kind="no_action",
            ),
            action_check=None,
            config=None,
        )

        self.assertFalse(result.round_completed)
        self.assertIsNone(result.public_interaction_prompt)
        self.assertIsNone(result.public_opposed_prompt)
        self.assertEqual(result.presentation.phase, PublicTurnPhase.INITIATIVE_EXECUTION)
        self.assertEqual(len(result.presentation.settlement_entries), 1)
        self.assertEqual(result.presentation.settlement_entries[0].actor_id, "npc_guard")
        self.assertEqual(result.presentation.settlement_entries[0].target_response_kind, "no_action")

        current_round = get_public_turn_state_in_save(save).current_round
        assert current_round is not None
        self.assertEqual(current_round.phase, PublicTurnPhase.INITIATIVE_EXECUTION)
        self.assertTrue(current_round.awaiting_player_action)
        self.assertEqual(current_round.current_actor_id, save.player_static_data.player_id)
        self.assertEqual(current_round.awaiting_player_action_phase, PublicTurnPhase.INITIATIVE_EXECUTION)
        self.assertEqual(current_round.executed_actor_ids, ["npc_guard"])
        self.assertIsNone(current_round.pending_interaction_prompt)
        self.assertNotIn("npc_bram", current_round.executed_actor_ids)

    def test_public_turn_initiative_interaction_response_consumes_player_turn(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_interaction_consumes_player_turn")
        state = get_public_turn_state_in_save(save)
        round_state = PublicTurnRound(
            round_id="ptround_interaction_consumes_player",
            round_number=1,
            phase=PublicTurnPhase.AWAITING_PLAYER_INTERACTION,
            initiative_declarations=[
                InitiativeDeclaration(
                    actor_id="npc_guard",
                    actor_name="Guard",
                    actor_type="npc",
                    declared_action="Guard reaches for the player.",
                    dex_modifier=1,
                    roll_d20=20,
                    total_initiative=21,
                ),
                InitiativeDeclaration(
                    actor_id=save.player_static_data.player_id,
                    actor_name=save.player_static_data.name,
                    actor_type="player",
                    declared_action="Take initiative",
                    dex_modifier=0,
                    roll_d20=19,
                    total_initiative=19,
                ),
            ],
            awaiting_player_action_phase=PublicTurnPhase.INITIATIVE_EXECUTION,
            pending_interaction_prompt=PublicTurnInteractionPrompt(
                prompt_id="prompt_interaction_consumes_player",
                round_id="ptround_interaction_consumes_player",
                phase=PublicTurnPhase.INITIATIVE_EXECUTION,
                source_actor_id="npc_guard",
                source_actor_name="Guard",
                source_action_type="check",
                source_action_summary="Guard grabs at your sleeve and tries to steer you away.",
                source_speech_text="Move.",
                source_action_prompt="actor=Guard; target=player; intent=steer the player away",
                source_world_impact_type=PublicTurnWorldImpactType.NON_WORLD,
                source_planned_requires_check=False,
                source_interaction_kind="block",
                target_actor_id=save.player_static_data.player_id,
                target_actor_name=save.player_static_data.name,
                target_actor_kind=PublicTurnActorType.PLAYER,
                suggested_target_label=save.player_static_data.name,
            ),
        )
        state.current_round = round_state
        state.awaiting_player_entry = False
        save_public_turn_state_in_save(save, state)

        with (
            patch("app.services.public_turn_candidates.public_turn_normal_actor_rows", return_value=[]),
            patch("app.services.public_turn_gm_push_service.random.randint", return_value=3),
        ):
            result = continue_round_in_save(
                save,
                submission=None,
                interaction_response=PublicTurnInteractionResponseSubmission(
                    prompt_id="prompt_interaction_consumes_player",
                    action_text="I go with the movement and give ground half a step.",
                    speech_text="Fine.",
                    response_kind="explicit_response",
                ),
                action_check=None,
                config=None,
            )

        self.assertTrue(result.round_completed)
        self.assertIsNone(get_public_turn_state_in_save(save).current_round)

    def test_public_turn_initiative_opposed_response_consumes_player_turn(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_opposed_consumes_player_turn")
        state = get_public_turn_state_in_save(save)
        round_state = PublicTurnRound(
            round_id="ptround_opposed_consumes_player",
            round_number=1,
            phase=PublicTurnPhase.AWAITING_PLAYER_OPPOSED,
            initiative_declarations=[
                InitiativeDeclaration(
                    actor_id="npc_guard",
                    actor_name="Guard",
                    actor_type="npc",
                    declared_action="Guard forces the issue.",
                    dex_modifier=1,
                    roll_d20=20,
                    total_initiative=21,
                ),
                InitiativeDeclaration(
                    actor_id=save.player_static_data.player_id,
                    actor_name=save.player_static_data.name,
                    actor_type="player",
                    declared_action="Take initiative",
                    dex_modifier=0,
                    roll_d20=19,
                    total_initiative=19,
                ),
            ],
            awaiting_player_action_phase=PublicTurnPhase.INITIATIVE_EXECUTION,
        )
        state.current_round = round_state
        state.awaiting_player_entry = False
        save_public_turn_state_in_save(save, state)
        prompt = PublicTurnOpposedPrompt(
            check_id="prompt_opposed_consumes_player",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.INITIATIVE_EXECUTION,
            source_actor_id="npc_guard",
            source_actor_name="Guard",
            source_action_summary="Guard lunges to shove you away from the doorway.",
            source_speech_text="Out.",
            source_interaction_kind="block",
            source_action_target_name=save.player_static_data.name,
            target_actor_id=save.player_static_data.player_id,
            target_actor_name=save.player_static_data.name,
            stakes_summary="If the guard wins, you lose the doorway.",
        )
        plan = PublicTurnOpposedPlanResponse(
            session_id=save.session_id,
            round_id=round_state.round_id,
            check_id=prompt.check_id,
            source_actor_id=prompt.source_actor_id,
            source_actor_name=prompt.source_actor_name,
            source_action_summary=prompt.source_action_summary,
            source_speech_text=prompt.source_speech_text,
            source_ability_used="strength",
            source_ability_modifier=1,
            target_actor_id=prompt.target_actor_id,
            target_actor_name=prompt.target_actor_name,
            target_action_summary="I plant my feet and knock his arm aside.",
            target_speech_text="No.",
            target_ability_used="dexterity",
            target_ability_modifier=2,
            check_task="hold the doorway",
            stakes_summary=prompt.stakes_summary,
        )
        action_result = ActionCheckResponse(
            session_id=save.session_id,
            actor_role_id=prompt.source_actor_id,
            actor_name=prompt.source_actor_name,
            actor_kind="npc",
            action_type="check",
            check_mode="action",
            source_context="public_turn",
            resolution_rule="opposed_actor",
            requires_check=True,
            ability_used="strength",
            ability_modifier=1,
            dc=12,
            check_task="hold the doorway",
            target_role_id=prompt.target_actor_id,
            target_name=prompt.target_actor_name,
            target_actor_kind="player",
            target_ability_used="dexterity",
            target_ability_modifier=2,
            dice_roll=11,
            total_score=12,
            target_dice_roll=15,
            target_total_score=17,
            contested_success=False,
            success=False,
            critical="none",
            time_spent_min=1,
            narrative="Guard loses the clash and the player holds the doorway.",
            applied_effects=[],
            relation_tag_suggestion=None,
            scene_events=[],
            state_sync=None,
            post_checks=None,
        )

        with (
            patch("app.services.public_turn_resolution.world.plan_public_turn_opposed_exchange", return_value=plan),
            patch("app.services.public_turn_resolution.world.action_check", return_value=action_result),
            patch("app.services.public_turn_candidates.public_turn_normal_actor_rows", return_value=[]),
            patch("app.services.public_turn_gm_push_service.random.randint", return_value=3),
        ):
            result = resume_round_after_opposed_in_save(
                save,
                phase_before_pause=PublicTurnPhase.INITIATIVE_EXECUTION,
                prompt=prompt,
                target_action_summary=plan.target_action_summary,
                target_speech_text=plan.target_speech_text,
                forced_dice_roll=15,
                config=None,
            )

        self.assertTrue(result.round_completed)
        self.assertIsNone(get_public_turn_state_in_save(save).current_round)

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

    def test_resolve_public_turn_segment_uses_reputation_hint_and_generates_opposed_summary(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_segment_reputation_hint")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        bram_role = next(item for item in save.role_pool if item.role_id == "npc_bram")
        actor_lookup = {
            "npc_bram": {
                "actor_id": "npc_bram",
                "name": bram_role.name,
                "actor_type": "team",
                "priority_reason": "test",
                "role": bram_role,
            }
        }
        plan = PublicTurnSegmentPlan(
            segment_id=f"{round_state.round_id}_segment_test",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.INITIATIVE_EXECUTION,
            actor_directives=[
                PublicTurnSegmentActorDirective(
                    actor_id="npc_bram",
                    actor_name=bram_role.name,
                    actor_type=PublicTurnActorType.TEAM,
                    phase=PublicTurnPhase.INITIATIVE_EXECUTION,
                    action_type="check",
                    action_summary="Bram plants his shoulder and drives straight into Erin's push.",
                    speech_text="Hold the line.",
                    action_prompt="Bram drives Erin back.",
                    action_target_actor_id="npc_erin",
                    action_target_name="鑹剧惓",
                    action_target_kind=PublicTurnActorType.NPC,
                    world_impact_type=PublicTurnWorldImpactType.WORLD,
                    target_actor_id="npc_erin",
                    target_name="鑹剧惓",
                    target_actor_kind="npc",
                    interaction_target_actor_id="npc_erin",
                    interaction_target_name="鑹剧惓",
                    interaction_target_kind=PublicTurnActorType.NPC,
                    interaction_kind="block",
                    interaction_requires_response=True,
                    target_response_action_summary="Erin braces in place and shoves back with both hands.",
                    target_response_speech_text="Not this time.",
                    target_response_world_impact_type=PublicTurnWorldImpactType.WORLD,
                    interaction_exchange_kind="world_exchange",
                    consent_state="rejected",
                    resolution_mode="opposed_actor",
                    resolution_rule="opposed_actor",
                    planned_requires_check=True,
                    planned_ability_used="strength",
                    planned_dc=12,
                    planned_check_task="drive Erin away from the player",
                    target_ability_used="dexterity",
                    target_ability_modifier=2,
                    specific_threat="If Erin breaks through, the team loses control of the square.",
                    stakes_summary="Bram and Erin collide head-on in the middle of the square.",
                    situation_delta_hint=4,
                    reputation_delta_hint=2,
                    pause_kind="none",
                )
            ],
            boundary=PublicTurnSegmentBoundary(boundary_kind="round_end", phase=PublicTurnPhase.INITIATIVE_EXECUTION),
        )
        action_result = ActionCheckResponse(
            session_id=save.session_id,
            actor_role_id="npc_bram",
            actor_name=bram_role.name,
            actor_kind="npc",
            action_type="check",
            check_mode="action",
            source_context="public_turn",
            resolution_rule="opposed_actor",
            requires_check=True,
            ability_used="strength",
            ability_modifier=2,
            dc=12,
            check_task="drive Erin away from the player",
            target_role_id="npc_erin",
            target_name="鑹剧惓",
            target_actor_kind="npc",
            target_ability_used="dexterity",
            target_ability_modifier=2,
            dice_roll=14,
            total_score=16,
            target_dice_roll=9,
            target_total_score=11,
            contested_success=True,
            success=True,
            critical="none",
            time_spent_min=1,
            narrative="Bram wins the clash and forces Erin back a step.",
            applied_effects=[],
            relation_tag_suggestion=None,
            scene_events=[],
            state_sync=None,
            post_checks=None,
        )

        with patch("app.services.public_turn_segment_service.public_scene_legacy._actor_check", return_value=action_result):
            segment = resolve_public_turn_segment(
                save,
                round_state=round_state,
                actor_lookup=actor_lookup,
                plan=plan,
                context_text="The player keeps the pressure on.",
                reputation_score=50,
                config=None,
            )

        self.assertEqual(len(segment.beats), 1)
        beat = segment.beats[0]
        assert beat.impact is not None
        assert beat.settlement is not None
        self.assertEqual(beat.impact.zone_reputation_delta, 2)
        self.assertEqual(beat.settlement.zone_reputation_delta, 2)
        self.assertNotEqual(beat.settlement.gm_resolution_summary, "")
        self.assertIn("鑹剧惓", beat.settlement.gm_resolution_summary)

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

    def test_invalid_reaction_tone_is_rejected_without_silent_sanitization(self) -> None:
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
            with self.assertRaises(ValidationError):
                continue_round_in_save(
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

    def test_initiative_actor_rows_alias_encounter_temp_npc_name_collision_with_team_member(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_temp_npc_name_collision")
        teammate_name = save.team_state.members[0].name
        save.encounter_state.encounters = [
            EncounterEntry(
                encounter_id="enc_public_turn",
                type="event",
                status="active",
                title="Square Dispute",
                description="A public argument pulls focus.",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                temporary_npcs=[
                    EncounterTemporaryNpc(
                        encounter_npc_id="encnpc_dup",
                        name=teammate_name,
                        title="Duplicate Name",
                        description="Bad duplicate of the teammate.",
                        speaking_style="brief",
                        agenda="confuse the scene",
                        zone_id="zone_square",
                        sub_zone_id="sub_square_1",
                    ),
                    EncounterTemporaryNpc(
                        encounter_npc_id="encnpc_watcher",
                        name="瑙傚療鑰?",
                        title="Watcher",
                        description="Keeps an eye on the crowd.",
                        speaking_style="brief",
                        agenda="contain the fight",
                        zone_id="zone_square",
                        sub_zone_id="sub_square_1",
                    ),
                ],
            )
        ]
        save.encounter_state.active_encounter_id = "enc_public_turn"

        rows = initiative_actor_rows(save, player_text="I scan the square.", config=None)

        actor_ids = {str(item.get("actor_id") or "") for item in rows}
        self.assertIn("npc_bram", actor_ids)
        self.assertIn("encnpc_watcher", actor_ids)
        self.assertIn("encnpc_dup", actor_ids)
        duplicate_row = next(item for item in rows if str(item.get("actor_id") or "") == "encnpc_dup")
        self.assertEqual(duplicate_row.get("name"), f"{teammate_name}（遭遇NPC）")

    def test_plan_public_turn_segment_forwards_scene_context_to_actor_planning(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_segment_context")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        actor_rows = [
            {
                "actor_id": "npc_guard",
                "name": "瀹堝崼",
                "actor_type": "npc",
                "role": next(item for item in save.role_pool if item.role_id == "npc_guard"),
                "priority_reason": "test",
            }
        ]
        scene_context = {
            "active_encounter": {
                "encounter_id": "enc_public_turn_context",
                "title": "Library Surge",
                "scene_summary": "The relic energy surge is flooding the public hall.",
            },
            "sub_zone_recent_turns": [
                {
                    "gm_narration": "The public hall is collapsing into chaos.",
                }
            ],
        }

        captured_scene_contexts: list[dict[str, object] | None] = []

        def _capture_actor_action(save, actor, *args, **kwargs):
            captured_scene_contexts.append(kwargs.get("scene_context"))
            actor_name = str(actor.get("name") or "Actor")
            return {
                "response_mode": "respond",
                "action_type": "check",
                "world_impact_type": "world",
                "visible_intent": f"{actor_name} moves to contain the surge.",
                "external_action_narration": f"{actor_name} moves to contain the surge.",
                "speech_line": "",
                "specific_threat": "The relic energy surge is still spreading across the hall.",
                "action_prompt": f"actor={actor_name}; intent=contain the surge",
                "target_label": "relic surge",
                "speech_target_label": "",
            }

        with patch(
            "app.services.public_turn_segment_service.public_scene_runtime._ai_actor_action",
            side_effect=_capture_actor_action,
        ):
            plan_public_turn_segment(
                save,
                round_state=round_state,
                actor_rows=actor_rows,
                phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
                player_text="I stabilize the nearest bystanders and make room to respond.",
                gm_summary="The public hall is collapsing into chaos.",
                scene_context=scene_context,
                audience_context={},
                prior_narration="",
                default_boundary_kind="round_end",
                config=None,
            )

        self.assertTrue(captured_scene_contexts)
        scene_context = captured_scene_contexts[0]
        self.assertIsNotNone(scene_context)
        assert scene_context is not None
        self.assertEqual(scene_context["active_encounter"]["encounter_id"], "enc_public_turn_context")
        self.assertEqual(scene_context["active_encounter"]["title"], "Library Surge")

    def test_plan_public_turn_segment_only_plans_next_actor_for_sequential_order(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_segment_sequential")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        actor_rows = [
            {
                "actor_id": "npc_erin",
                "name": next(item for item in save.role_pool if item.role_id == "npc_erin").name,
                "actor_type": "npc",
                "role": next(item for item in save.role_pool if item.role_id == "npc_erin"),
                "priority_reason": "test_first",
            },
            {
                "actor_id": "npc_guard",
                "name": next(item for item in save.role_pool if item.role_id == "npc_guard").name,
                "actor_type": "npc",
                "role": next(item for item in save.role_pool if item.role_id == "npc_guard"),
                "priority_reason": "test_second",
            },
        ]

        planned_actor_ids: list[str] = []

        def _capture_actor_action(save, actor, *args, **kwargs):
            planned_actor_ids.append(str(actor.get("actor_id") or ""))
            actor_name = str(actor.get("name") or "Actor")
            return {
                "response_mode": "respond",
                "action_type": "check",
                "world_impact_type": "world",
                "visible_intent": f"{actor_name} reacts first.",
                "external_action_narration": f"{actor_name} reacts first.",
                "speech_line": "",
                "specific_threat": "The immediate scene is still unfolding.",
                "action_prompt": f"actor={actor_name}; intent=react first",
                "target_label": "",
                "speech_target_label": "",
            }

        with (
            patch("app.services.public_turn_segment_service.public_scene_runtime._ai_actor_action", side_effect=_capture_actor_action),
            patch("app.services.public_turn_segment_service._planner_overrides", return_value={}),
        ):
            plan = plan_public_turn_segment(
                save,
                round_state=round_state,
                actor_rows=actor_rows,
                phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
                player_text="I step back and watch the exchange.",
                gm_summary="The public hall is tense.",
                scene_context={"gm_narration": "The public hall is tense."},
                audience_context={},
                prior_narration="",
                default_boundary_kind="round_end",
                config=None,
            )

        self.assertEqual(planned_actor_ids, ["npc_erin"])
        self.assertEqual([directive.actor_id for directive in plan.actor_directives], ["npc_erin"])

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

    def test_team_actor_turn_uses_ai_reputation_delta_hint(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_team_reputation_hint")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        actor = {
            "actor_id": "npc_bram",
            "name": next(item for item in save.role_pool if item.role_id == "npc_bram").name,
            "actor_type": "team",
            "priority_reason": "test",
            "role": next(item for item in save.role_pool if item.role_id == "npc_bram"),
        }

        with (
            patch(
                "app.services.public_turn_resolution.public_scene_runtime._ai_actor_action",
                return_value={
                    "external_action_narration": "Bram steps between the crowd and the player to calm the square.",
                    "speech_line": "Back off.",
                    "visible_intent": "Win public space for the team.",
                    "specific_threat": "The crowd is still on edge.",
                    "target_label": "",
                    "action_type": "check",
                    "action_prompt": "Bram stabilizes the crowd.",
                    "situation_delta_hint": 4,
                    "reputation_delta_hint": 2,
                },
            ),
            patch("app.services.public_turn_resolution.public_scene_runtime.should_force_public_action_check", return_value=False),
        ):
            _, impact, settlement, _, _ = resolve_ai_actor_turn(
                save,
                actor=actor,
                player_text="The player holds position.",
                gm_summary="Public turn continues.",
                round_state=round_state,
                scene_context={},
                audience_context={},
                reputation_score=50,
                config=None,
            )

        assert impact is not None
        assert settlement is not None
        self.assertEqual(impact.zone_reputation_delta, 2)
        self.assertEqual(settlement.zone_reputation_delta, 2)

    def test_multiple_team_actor_turns_each_can_change_reputation(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_multiple_team_reputation_scope")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        role = next(item for item in save.role_pool if item.role_id == "npc_bram")
        actor_one = {
            "actor_id": "npc_bram",
            "name": "布莱姆",
            "actor_type": "team",
            "priority_reason": "test",
            "role": role,
        }
        actor_two = {
            "actor_id": "npc_bram_second",
            "name": "布莱姆二号",
            "actor_type": "team",
            "priority_reason": "test",
            "role": role,
        }

        with (
            patch(
                "app.services.public_turn_resolution.public_scene_runtime._ai_actor_action",
                return_value={
                    "external_action_narration": "布莱姆稳住了正在扩散的骚动。",
                    "speech_line": "都站稳。",
                    "visible_intent": "替队伍稳住公开场面。",
                    "specific_threat": "围观者的恐慌还在蔓延。",
                    "target_label": "",
                    "action_type": "check",
                    "action_prompt": "布莱姆稳住人群",
                    "situation_delta_hint": 4,
                },
            ),
            patch("app.services.public_turn_resolution.public_scene_runtime.should_force_public_action_check", return_value=False),
        ):
            _, impact_one, settlement_one, _, _ = resolve_ai_actor_turn(
                save,
                actor=actor_one,
                player_text="玩家继续稳住场面。",
                gm_summary="公开回合继续。",
                round_state=round_state,
                scene_context={},
                audience_context={},
                reputation_score=50,
                config=None,
            )
            _, impact_two, settlement_two, _, _ = resolve_ai_actor_turn(
                save,
                actor=actor_two,
                player_text="玩家继续稳住场面。",
                gm_summary="公开回合继续。",
                round_state=round_state,
                scene_context={},
                audience_context={},
                reputation_score=50,
                config=None,
            )

        assert impact_one is not None
        assert impact_two is not None
        assert settlement_one is not None
        assert settlement_two is not None
        self.assertEqual(impact_one.zone_reputation_delta, 1)
        self.assertEqual(impact_two.zone_reputation_delta, 1)
        self.assertEqual(settlement_one.zone_reputation_delta, 1)
        self.assertEqual(settlement_two.zone_reputation_delta, 1)

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

    def test_extract_resolution_summary_text_keeps_multiline_content(self) -> None:
        text = "第一句回应。\n第二句描写。"

        summary = _extract_resolution_summary_text(text, limit=120)

        self.assertIn("第一句回应。", summary)
        self.assertIn("第二句描写。", summary)

    def test_build_settlement_fragment_includes_opposed_result_outcome(self) -> None:
        settlement = PublicTurnSettlementEntry(
            entry_id="ptround_test_1",
            round_id="ptround_test",
            phase=PublicTurnPhase.INITIATIVE_EXECUTION,
            order_index=0,
            actor_id="npc_guard",
            actor_name="Guard",
            actor_type=PublicTurnActorType.NPC,
            action_summary="Guard lunges forward and tries to wrench the player aside.",
            speech_text="Move.",
            opposed_target_name="Player",
            opposed_target_action="Player braces in place and knocks the guard's arm aside.",
            interaction_resolution="rejected_opposed",
            check=PublicTurnSettlementCheck(
                resolution_rule="opposed_actor",
                ability_used="strength",
                ability_modifier=1,
                dice_roll=11,
                total_score=12,
                dc=12,
                target_name="Player",
                target_ability_used="dexterity",
                target_ability_modifier=2,
                target_dice_roll=15,
                target_total_score=17,
                success=False,
                critical="none",
                comparison_text="Guard d20(11) +1 = 12; Player d20(15) +2 = 17.",
                outcome_text="Failure",
            ),
            situation_delta=0,
            zone_reputation_delta=0,
            relation_deltas=[],
            team_affinity_deltas=[],
            hp_changes=[],
            environment_shift=0,
        )

        narration = build_settlement_fragment(settlement)

        self.assertIn("Player braces in place", narration)
        self.assertIn("没能压过Player的回应", narration)

    def test_build_settlement_fragment_prefers_gm_resolution_summary_for_opposed_result(self) -> None:
        settlement = PublicTurnSettlementEntry(
            entry_id="ptround_test_summary_1",
            round_id="ptround_test_summary",
            phase=PublicTurnPhase.INITIATIVE_EXECUTION,
            order_index=0,
            actor_id="npc_guard",
            actor_name="Guard",
            actor_type=PublicTurnActorType.NPC,
            action_summary="Guard lunges forward and tries to wrench the player aside.",
            speech_text="Move.",
            opposed_target_name="Player",
            opposed_target_action="Player braces in place and knocks the guard's arm aside.",
            interaction_resolution="rejected_opposed",
            check=PublicTurnSettlementCheck(
                resolution_rule="opposed_actor",
                ability_used="strength",
                ability_modifier=1,
                dice_roll=11,
                total_score=12,
                dc=12,
                target_name="Player",
                target_ability_used="dexterity",
                target_ability_modifier=2,
                target_dice_roll=15,
                target_total_score=17,
                success=False,
                critical="none",
                comparison_text="Guard d20(11) +1 = 12; Player d20(15) +2 = 17.",
                outcome_text="Failure",
            ),
            gm_resolution_summary="Player plants in place, jars the guard's shoulder aside, and the whole shove loses momentum on impact.",
            situation_delta=0,
            zone_reputation_delta=0,
            relation_deltas=[],
            team_affinity_deltas=[],
            hp_changes=[],
            environment_shift=0,
        )

        narration = build_settlement_fragment(settlement)

        self.assertIn("Player plants in place, jars the guard's shoulder aside", narration)
        self.assertNotIn("没能压过Player的回应", narration)

    def test_resolve_opposed_prompt_submission_generates_resolution_summary(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_opposed_resolution_summary")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        prompt = PublicTurnOpposedPrompt(
            check_id=f"{round_state.round_id}_npc_guard_opposed",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.INITIATIVE_EXECUTION,
            source_actor_id="npc_guard",
            source_actor_name="Guard",
            source_action_summary="Guard lunges to wrench the player aside and force a path open.",
            source_speech_text="Move.",
            source_interaction_kind="block",
            source_action_target_name=save.player_static_data.name,
            source_speech_target_name=save.player_static_data.name,
            target_actor_id=save.player_static_data.player_id,
            target_actor_name=save.player_static_data.name,
            stakes_summary="If the guard forces through, the player loses the doorway.",
        )
        plan = PublicTurnOpposedPlanResponse(
            session_id=save.session_id,
            round_id=round_state.round_id,
            check_id=prompt.check_id,
            source_actor_id=prompt.source_actor_id,
            source_actor_name=prompt.source_actor_name,
            source_action_summary=prompt.source_action_summary,
            source_speech_text=prompt.source_speech_text,
            source_ability_used="strength",
            source_ability_modifier=1,
            target_actor_id=prompt.target_actor_id,
            target_actor_name=prompt.target_actor_name,
            target_action_summary="Player plants in place and knocks the guard's arm away.",
            target_speech_text="Not happening.",
            target_ability_used="dexterity",
            target_ability_modifier=2,
            check_task="force through the doorway",
            stakes_summary=prompt.stakes_summary,
        )
        action_result = ActionCheckResponse(
            session_id=save.session_id,
            actor_role_id=prompt.source_actor_id,
            actor_name=prompt.source_actor_name,
            actor_kind="npc",
            action_type="check",
            check_mode="action",
            source_context="public_turn",
            resolution_rule="opposed_actor",
            requires_check=True,
            ability_used="strength",
            ability_modifier=1,
            dc=12,
            check_task="force through the doorway",
            target_role_id=prompt.target_actor_id,
            target_name=prompt.target_actor_name,
            target_actor_kind="player",
            target_ability_used="dexterity",
            target_ability_modifier=2,
            dice_roll=11,
            total_score=12,
            target_dice_roll=15,
            target_total_score=17,
            contested_success=False,
            success=False,
            critical="none",
            time_spent_min=1,
            narrative="Guard tries to force the player back but loses the clash.",
            applied_effects=[],
            relation_tag_suggestion=None,
            scene_events=[],
            state_sync=None,
            post_checks=None,
        )

        with (
            patch("app.services.public_turn_resolution.world.plan_public_turn_opposed_exchange", return_value=plan),
            patch("app.services.public_turn_resolution.world.action_check", return_value=action_result),
        ):
            _, impact, settlement, resolved = resolve_opposed_prompt_submission(
                save,
                session_id=save.session_id,
                prompt=prompt,
                target_action_summary=plan.target_action_summary,
                target_speech_text=plan.target_speech_text,
                forced_dice_roll=15,
                round_state=round_state,
                config=None,
            )

        self.assertIs(resolved, action_result)
        self.assertIsNotNone(impact)
        self.assertNotEqual(settlement.gm_resolution_summary, "")
        self.assertIn(prompt.target_actor_name, settlement.gm_resolution_summary)
        self.assertIn(settlement.gm_resolution_summary, build_settlement_fragment(settlement))

    def test_resolve_opposed_prompt_submission_uses_prompt_hints_for_team_actor(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_opposed_prompt_hints")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        state = get_public_turn_state_in_save(save)
        round_state = state.current_round
        assert round_state is not None
        bram_name = next(item for item in save.role_pool if item.role_id == "npc_bram").name
        prompt = PublicTurnOpposedPrompt(
            check_id=f"{round_state.round_id}_npc_bram_opposed",
            round_id=round_state.round_id,
            phase=PublicTurnPhase.INITIATIVE_EXECUTION,
            source_actor_id="npc_bram",
            source_actor_name=bram_name,
            source_action_summary="Bram slams into Erin to keep her away from the player.",
            source_speech_text="Stay back.",
            source_interaction_kind="block",
            source_action_target_name="鑹剧惓",
            source_situation_delta_hint=7,
            source_reputation_delta_hint=2,
            target_actor_id="npc_erin",
            target_actor_name="鑹剧惓",
            stakes_summary="If Bram loses the clash, Erin breaks the team line.",
        )
        plan = PublicTurnOpposedPlanResponse(
            session_id=save.session_id,
            round_id=round_state.round_id,
            check_id=prompt.check_id,
            source_actor_id=prompt.source_actor_id,
            source_actor_name=prompt.source_actor_name,
            source_action_summary=prompt.source_action_summary,
            source_speech_text=prompt.source_speech_text,
            source_ability_used="strength",
            source_ability_modifier=2,
            target_actor_id=prompt.target_actor_id,
            target_actor_name=prompt.target_actor_name,
            target_action_summary="Erin braces and throws her weight back into Bram.",
            target_speech_text="Move.",
            target_ability_used="dexterity",
            target_ability_modifier=2,
            check_task="hold Erin away from the player",
            stakes_summary=prompt.stakes_summary,
        )
        action_result = ActionCheckResponse(
            session_id=save.session_id,
            actor_role_id=prompt.source_actor_id,
            actor_name=prompt.source_actor_name,
            actor_kind="npc",
            action_type="check",
            check_mode="action",
            source_context="public_turn",
            resolution_rule="opposed_actor",
            requires_check=True,
            ability_used="strength",
            ability_modifier=2,
            dc=12,
            check_task="hold Erin away from the player",
            target_role_id=prompt.target_actor_id,
            target_name=prompt.target_actor_name,
            target_actor_kind="npc",
            target_ability_used="dexterity",
            target_ability_modifier=2,
            dice_roll=8,
            total_score=10,
            target_dice_roll=14,
            target_total_score=16,
            contested_success=False,
            success=False,
            critical="none",
            time_spent_min=1,
            narrative="Bram loses the shove and Erin forces him half a step back.",
            applied_effects=[],
            relation_tag_suggestion=None,
            scene_events=[],
            state_sync=None,
            post_checks=None,
        )

        with (
            patch("app.services.public_turn_resolution.world.plan_public_turn_opposed_exchange", return_value=plan),
            patch("app.services.public_turn_resolution.world.action_check", return_value=action_result),
        ):
            _, impact, settlement, resolved = resolve_opposed_prompt_submission(
                save,
                session_id=save.session_id,
                prompt=prompt,
                target_action_summary=plan.target_action_summary,
                target_speech_text=plan.target_speech_text,
                forced_dice_roll=14,
                round_state=round_state,
                config=None,
            )

        self.assertIs(resolved, action_result)
        assert impact is not None
        self.assertEqual(impact.situation_delta, 3)
        self.assertEqual(impact.zone_reputation_delta, 2)
        self.assertEqual(settlement.situation_delta, 3)
        self.assertEqual(settlement.zone_reputation_delta, 2)

    def test_plan_action_check_auto_action_type_uses_ai_output(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_auto_action_type")

        with patch(
            "app.services.world_service._ai_action_plan",
            return_value={
                "action_type": "attack",
                "ability_used": "intelligence",
                "dc": 14,
                "time_spent_min": 1,
                "requires_check": True,
                "check_task": "cast fireball into the clustered enemies",
            },
        ):
            plan = plan_action_check(
                ActionCheckPlanRequest(
                    session_id=save.session_id,
                    actor_role_id=save.player_static_data.player_id,
                    action_type="auto",
                    action_prompt="Cast Fireball into the clustered enemies.",
                    source_context="public_turn",
                    config=None,
                )
            )

        self.assertEqual(plan.action_type, "attack")
        self.assertEqual(plan.ability_used, "intelligence")

    def test_attack_assessment_uses_ai_definition_id_without_backend_text_matching(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_attack_id_only")

        with patch(
            "app.services.public_turn_attack_service.create_sync_client",
            return_value=_FakeSyncClient(
                (
                    '{"attack_kind":"aoe_attack","attack_basis":"spell","attack_definition_id":"fireball",'
                    '"attack_definition_name":"火球术","attack_area_shape":"sphere","attack_area_radius_m":5,'
                    '"attack_area_length_m":0,"self_target_policy":"can_include_self","attack_ability_used":"intelligence",'
                    '"candidate_target_names":["守卫","布莱姆"]}'
                )
            ),
        ):
            assessment = assess_public_turn_attack(
                save,
                actor_role_id=save.player_static_data.player_id,
                actor_name=save.player_static_data.name,
                action_summary="我朝人群正中甩出一颗炽热火球。",
                speech_text="趴下。",
                action_prompt="玩家释放一发范围法术。",
                fallback_target_name="守卫",
                config=self._ai_config(),
            )

        basis, definition = resolve_attack_definition(
            save,
            actor_role_id=save.player_static_data.player_id,
            attack_definition_id=str(assessment.get("attack_definition_id") or ""),
            attack_basis_hint=str(assessment.get("attack_basis") or ""),
        )
        self.assertEqual(assessment["attack_definition_id"], "fireball")
        self.assertEqual(assessment["attack_definition_name"], "火球术")
        self.assertEqual(assessment["candidate_target_names"], ["守卫", "布莱姆"])
        self.assertEqual(basis, "spell")
        self.assertIsNotNone(definition)
        self.assertEqual(definition.definition_id, "fireball")  # type: ignore[union-attr]

    def test_attack_assessment_without_ai_does_not_guess_fireball_from_text(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_no_attack_keyword_fallback")

        assessment = assess_public_turn_attack(
            save,
            actor_role_id=save.player_static_data.player_id,
            actor_name=save.player_static_data.name,
            action_summary="我把火球术砸向人群中心。",
            speech_text="烧起来。",
            action_prompt="玩家说他要用火球术。",
            fallback_target_name="守卫",
            config=None,
        )

        self.assertEqual(assessment["attack_kind"], "ordinary_action")
        self.assertEqual(assessment["attack_basis"], "other")
        self.assertEqual(assessment["attack_definition_id"], "")
        self.assertEqual(assessment["candidate_target_names"], [])

    def test_attack_assessment_recognizes_war_art_attack(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_war_art_assessment")

        with patch(
            "app.services.public_turn_attack_service.create_sync_client",
            return_value=_FakeSyncClient(
                (
                    '{"attack_kind":"targeted_attack","attack_basis":"war_art","attack_definition_id":"power_strike",'
                    '"attack_definition_name":"强力斩","attack_area_shape":"none","self_target_policy":"never",'
                    '"attack_ability_used":"strength","candidate_target_names":["瀹堝崼"]}'
                )
            ),
        ):
            assessment = assess_public_turn_attack(
                save,
                actor_role_id=save.player_static_data.player_id,
                actor_name=save.player_static_data.name,
                action_summary="我使用强力斩劈向守卫。",
                speech_text="",
                action_prompt="玩家使用强力斩攻击守卫。",
                fallback_target_name="瀹堝崼",
                config=self._ai_config(),
            )

        basis, definition = resolve_attack_definition(
            save,
            actor_role_id=save.player_static_data.player_id,
            attack_definition_id=str(assessment.get("attack_definition_id") or ""),
            attack_basis_hint=str(assessment.get("attack_basis") or ""),
        )
        self.assertEqual(assessment["attack_kind"], "targeted_attack")
        self.assertEqual(assessment["attack_basis"], "war_art")
        self.assertEqual(assessment["attack_definition_id"], "power_strike")
        self.assertEqual(basis, "war_art")
        self.assertIsNotNone(definition)
        self.assertEqual(definition.definition_id, "power_strike")  # type: ignore[union-attr]
        return
        self.assertEqual(assessment["candidate_target_names"], ["瀹堝崼"])
        self.assertEqual(basis, "war_art")
        self.assertIsNotNone(definition)
        self.assertEqual(definition.definition_id, "power_strike")  # type: ignore[union-attr]

    def test_resolve_player_attack_submission_consumes_war_art_points(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_war_art_cost")
        save.player_static_data.dnd5e_sheet.war_arts = ["power_strike"]
        save.player_static_data.dnd5e_sheet.martial_points_current = 2
        guard = next(item for item in save.role_pool if item.role_id == "npc_guard")

        with patch(
            "app.services.public_turn_resolution.assess_public_turn_attack",
            return_value={
                "attack_kind": "targeted_attack",
                "attack_basis": "war_art",
                "attack_definition_id": "power_strike",
                "attack_definition_name": "power_strike",
                "attack_area_shape": "none",
                "attack_area_radius_m": 0.0,
                "attack_area_length_m": 0.0,
                "self_target_policy": "never",
                "candidate_target_names": [guard.name],
                "attack_ability_used": "strength",
            },
        ):
            events, impact, settlement, action_result, attack_prompt = resolve_player_attack_submission(
                save,
                session_id=save.session_id,
                action_text="鎴戜娇鐢ㄥ己鍔涙柀鍔堝悜瀹堝崼銆?",
                speech_text="",
                round_state=PublicTurnRound(round_id="round_war_art_cost"),
                action_check=None,
                config=None,
            )

        self.assertIsNone(attack_prompt)
        self.assertIsNotNone(settlement)
        self.assertEqual(settlement.attack_basis, "war_art")
        self.assertEqual(save.player_static_data.dnd5e_sheet.martial_points_current, 1)
        self.assertTrue(events)
        self.assertIsNotNone(impact)
        self.assertIsNone(action_result)

    def test_attack_response_without_ai_does_not_guess_effective_defense_from_text(self) -> None:
        classification = classify_attack_response(
            source_actor_name="守卫",
            source_action_summary="守卫将火球朝你身后甩来。",
            source_speech_text="站住。",
            target_actor_name="玩家",
            response_action_text="我翻滚闪开并用斗篷挡住爆焰。",
            response_speech_text="打不中我。",
            response_kind="explicit_response",
            config=None,
        )

        self.assertEqual(classification["world_impact_type"], "non_world")
        self.assertFalse(classification["effective_against_attack"])

    def test_prepare_npc_attack_prompt_uses_fallback_target_name_when_ai_misses_candidate_target(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_npc_attack_fallback_target")
        guard = next(item for item in save.role_pool if item.role_id == "npc_guard")

        with patch(
            "app.services.public_turn_resolution.assess_public_turn_attack",
            return_value={
                "attack_kind": "targeted_attack",
                "attack_basis": "weapon",
                "attack_definition_id": "",
                "attack_definition_name": "",
                "attack_area_shape": "none",
                "attack_area_radius_m": 0.0,
                "attack_area_length_m": 0.0,
                "self_target_policy": "never",
                "candidate_target_names": [],
                "attack_ability_used": "strength",
            },
        ):
            prompt = prepare_npc_attack_prompt(
                save,
                source_actor_id=guard.role_id,
                source_actor_name=guard.name,
                source_actor_type="npc",
                source_action_summary="Guard lunges toward the player.",
                source_speech_text="",
                source_action_prompt="Guard attacks the player directly.",
                source_action_target_name=save.player_static_data.name,
                round_state=PublicTurnRound(round_id="round_npc_attack_fallback"),
                situation_delta_hint=0,
                reputation_delta_hint=0,
                config=None,
            )

        self.assertIsNotNone(prompt)
        assert prompt is not None
        self.assertEqual(prompt.current_target_actor_id, save.player_static_data.player_id)
        self.assertIn(save.player_static_data.name, prompt.threatened_target_names)

    def test_resolve_player_submission_applies_ai_aoe_damage_to_multiple_targets(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_player_aoe_damage")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        round_state = get_public_turn_state_in_save(save).current_round
        assert round_state is not None
        guard = next(item for item in save.role_pool if item.role_id == "npc_guard")
        bram = next(item for item in save.role_pool if item.role_id == "npc_bram")
        guard.profile.dnd5e_sheet.hit_points.maximum = 18
        guard.profile.dnd5e_sheet.hit_points.current = 18
        bram.profile.dnd5e_sheet.hit_points.maximum = 14
        bram.profile.dnd5e_sheet.hit_points.current = 14
        action_result = ActionCheckResponse(
            session_id=save.session_id,
            actor_role_id=save.player_static_data.player_id,
            actor_name=save.player_static_data.name,
            actor_kind="player",
            action_type="attack",
            check_mode="action",
            source_context="public_turn",
            resolution_rule="static_dc",
            requires_check=True,
            ability_used="intelligence",
            ability_modifier=3,
            dc=13,
            check_task="cast fireball",
            target_role_id=guard.role_id,
            target_name=guard.name,
            target_actor_kind="npc",
            target_ability_used=None,
            target_ability_modifier=None,
            dice_roll=15,
            total_score=18,
            target_dice_roll=None,
            target_total_score=None,
            contested_success=None,
            success=True,
            critical="none",
            time_spent_min=1,
            narrative="The fireball blossoms across the crowd.",
            applied_effects=[],
            relation_tag_suggestion=None,
            scene_events=[],
            state_sync=None,
            post_checks=None,
        )

        with (
            patch("app.services.public_turn_resolution.world.action_check", return_value=action_result),
            patch(
                "app.services.public_turn_resolution.assess_public_turn_attack",
                return_value={
                    "attack_kind": "aoe_attack",
                    "attack_basis": "spell",
                    "attack_definition_id": "",
                    "attack_definition_name": "Fireball",
                    "attack_area_shape": "sphere",
                    "attack_area_radius_m": 5.0,
                    "attack_area_length_m": 0.0,
                    "self_target_policy": "can_include_self",
                    "candidate_target_names": [guard.name, bram.name],
                    "attack_ability_used": "intelligence",
                },
            ),
            patch(
                "app.services.public_turn_resolution._ai_public_turn_damage_bundle",
                return_value={
                    "effect_kind": "damage",
                    "area_mode": "sphere",
                    "rules_basis": "dnd5e_spell",
                    "spell_name": "Fireball",
                    "damage_application_mode": "on_success",
                    "damage_type": "fire",
                    "base_damage": 8,
                    "affected_targets": [
                        {"target_label": guard.name},
                        {"target_label": bram.name},
                    ],
                    "reason": "Fireball catches both visible targets in the same blast radius.",
                },
            ),
        ):
            events, impact, settlement, resolved = resolve_player_submission(
                save,
                session_id=save.session_id,
                action_text="I cast Fireball into the clustered enemies.",
                speech_text="Burn.",
                round_state=round_state,
                action_check=PublicTurnPlayerActionCheck(
                    action_type="attack",
                    source_context="public_turn",
                    resolution_rule="static_dc",
                    planned_requires_check=True,
                    planned_ability_used="intelligence",
                    planned_dc=13,
                    planned_time_spent_min=1,
                    planned_check_task="cast fireball",
                    forced_dice_roll=15,
                    target_role_id=guard.role_id,
                    target_name=guard.name,
                    target_actor_kind="npc",
                ),
                config=None,
            )

        self.assertIs(resolved, action_result)
        self.assertEqual(len(impact.hp_changes), 2)
        self.assertEqual(len(settlement.hp_changes), 2)
        self.assertEqual(guard.profile.dnd5e_sheet.hit_points.current, 10)
        self.assertEqual(bram.profile.dnd5e_sheet.hit_points.current, 6)
        self.assertTrue(any("fire damage" in event.content for event in events))

    def test_resolve_ai_actor_turn_applies_damage_to_player_and_marks_dying(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_npc_damage_player")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        round_state = get_public_turn_state_in_save(save).current_round
        assert round_state is not None
        save.player_static_data.dnd5e_sheet.hit_points.current = 6
        actor = {
            "actor_id": "npc_guard",
            "name": next(item for item in save.role_pool if item.role_id == "npc_guard").name,
            "actor_type": "npc",
            "role": next(item for item in save.role_pool if item.role_id == "npc_guard"),
        }
        action_result = ActionCheckResponse(
            session_id=save.session_id,
            actor_role_id="npc_guard",
            actor_name=actor["name"],
            actor_kind="npc",
            action_type="attack",
            check_mode="action",
            source_context="public_turn",
            resolution_rule="static_dc",
            requires_check=True,
            ability_used="dexterity",
            ability_modifier=2,
            dc=12,
            check_task="launch a scorching bolt",
            target_role_id=save.player_static_data.player_id,
            target_name=save.player_static_data.name,
            target_actor_kind="player",
            target_ability_used=None,
            target_ability_modifier=None,
            dice_roll=14,
            total_score=16,
            target_dice_roll=None,
            target_total_score=None,
            contested_success=None,
            success=True,
            critical="none",
            time_spent_min=1,
            narrative="The bolt slams into the player before they can clear the lane.",
            applied_effects=[],
            relation_tag_suggestion=None,
            scene_events=[],
            state_sync=None,
            post_checks=None,
        )

        with (
            patch(
                "app.services.public_turn_resolution.public_scene_runtime._ai_actor_action",
                return_value={
                    "response_mode": "respond",
                    "action_type": "attack",
                    "world_impact_type": "world",
                    "visible_intent": "Guard whips a scorching bolt straight at the player.",
                    "external_action_narration": "Guard whips a scorching bolt straight at the player.",
                    "speech_line": "",
                    "specific_threat": "The bolt can burn the player down immediately.",
                    "action_prompt": "Guard launches a scorching bolt into the player's chest.",
                    "target_label": save.player_static_data.name,
                    "speech_target_label": "",
                },
            ),
            patch(
                "app.services.public_turn_resolution.assess_public_turn_attack",
                return_value={
                    "attack_kind": "targeted_attack",
                    "attack_basis": "spell",
                    "attack_definition_id": "scorching_ray",
                    "attack_definition_name": "Scorching Ray",
                    "attack_area_shape": "none",
                    "attack_area_radius_m": 0.0,
                    "attack_area_length_m": 0.0,
                    "self_target_policy": "never",
                    "candidate_target_names": [save.player_static_data.name],
                    "attack_ability_used": "intelligence",
                },
            ),
            patch("app.services.public_turn_resolution.public_scene_legacy._actor_check", return_value=action_result),
            patch(
                "app.services.public_turn_resolution._ai_public_turn_damage_bundle",
                return_value={
                    "effect_kind": "damage",
                    "area_mode": "single",
                    "rules_basis": "dnd5e_spell",
                    "spell_name": "Scorching Ray",
                    "damage_application_mode": "on_success",
                    "damage_type": "fire",
                    "base_damage": 7,
                    "affected_targets": [{"target_label": save.player_static_data.name}],
                    "reason": "The spell is direct fire damage against the player.",
                },
            ),
        ):
            _, impact, settlement, pending_reaction, opposed_prompt = resolve_ai_actor_turn(
                save,
                actor=actor,
                player_text="I keep moving.",
                gm_summary="Hostile public turn.",
                round_state=round_state,
                scene_context={},
                audience_context={},
                reputation_score=50,
                config=None,
            )

        self.assertIsNone(pending_reaction)
        self.assertIsNone(opposed_prompt)
        assert impact is not None
        assert settlement is not None
        self.assertEqual(save.player_static_data.dnd5e_sheet.hit_points.current, 0)
        self.assertEqual(save.player_static_data.dnd5e_sheet.death_state.life_status, "dying")
        self.assertEqual(save.player_static_data.dnd5e_sheet.role_action_status, "death_saving")
        self.assertEqual(len(impact.hp_changes), 1)
        self.assertEqual(impact.hp_changes[0].target_name, save.player_static_data.name)
        self.assertEqual(settlement.hp_changes[0].hp_after, 0)

    def test_resolve_ai_actor_turn_consumes_spell_slot_for_spell_action(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_npc_spell_slot")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        round_state = get_public_turn_state_in_save(save).current_round
        assert round_state is not None
        actor_role = next(item for item in save.role_pool if item.role_id == "npc_guard")
        actor_role.profile.dnd5e_sheet.spells = ["Fire Bolt"]
        actor_role.profile.dnd5e_sheet.spell_slots_max.level_1 = 1
        actor_role.profile.dnd5e_sheet.spell_slots_current.level_1 = 1

        actor = {
            "actor_id": actor_role.role_id,
            "name": actor_role.name,
            "actor_type": "npc",
            "role": actor_role,
        }

        with (
            patch(
                "app.services.public_scene_runtime_v2._ai_actor_action",
                return_value={
                    "response_mode": "respond",
                    "action_type": "check",
                    "world_impact_type": "world",
                    "visible_intent": "guard uses fire bolt to hold the front line.",
                    "external_action_narration": "瀹堝崼使用火焰箭，火光沿着前方炸开。",
                    "speech_line": "",
                    "specific_threat": "",
                    "action_prompt": "actor=瀹堝崼; intent=use fire bolt",
                    "target_label": "",
                    "speech_target_label": "",
                },
            ),
            patch("app.services.public_scene_runtime_v2.should_force_public_action_check", return_value=False),
        ):
            _, impact, settlement, pending_reaction, opposed_prompt = resolve_ai_actor_turn(
                save,
                actor=actor,
                player_text="I wait.",
                gm_summary="Hostile public turn.",
                round_state=round_state,
                scene_context={},
                audience_context={},
                reputation_score=50,
                config=None,
            )

        self.assertIsNone(opposed_prompt)
        self.assertIsNotNone(impact)
        self.assertIsNotNone(settlement)
        self.assertEqual(actor_role.profile.dnd5e_sheet.spell_slots_current.level_1, 0)

    def test_public_turn_player_turn_in_death_saving_returns_death_save_prompt(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_player_death_save_prompt")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        save.player_static_data.dnd5e_sheet.hit_points.current = 0
        save.player_static_data.dnd5e_sheet.death_state.life_status = "dying"
        save.player_static_data.dnd5e_sheet.role_action_status = "death_saving"

        result = continue_round_in_save(
            save,
            submission=PublicTurnActionSubmission(
                actor_id=save.player_static_data.player_id,
                action_text="",
                speech_text="I can still speak.",
                source_phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
                forced_first=False,
            ),
            action_check=None,
            config=None,
        )

        self.assertIsNotNone(result.death_save_prompt)
        assert result.death_save_prompt is not None
        self.assertEqual(result.death_save_prompt.actor_id, save.player_static_data.player_id)
        self.assertEqual(result.death_save_prompt.speech_only, True)
        self.assertEqual(result.presentation.phase, PublicTurnPhase.AWAITING_PLAYER_DEATH_SAVE)
        current_round = get_public_turn_state_in_save(save).current_round
        assert current_round is not None
        self.assertEqual(current_round.phase, PublicTurnPhase.AWAITING_PLAYER_DEATH_SAVE)
        self.assertIsNotNone(current_round.pending_death_save_prompt)

    def test_public_turn_player_turn_in_death_saving_rejects_action_text(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_player_death_save_speech_only")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        save.player_static_data.dnd5e_sheet.hit_points.current = 0
        save.player_static_data.dnd5e_sheet.death_state.life_status = "dying"
        save.player_static_data.dnd5e_sheet.role_action_status = "death_saving"

        with self.assertRaisesRegex(ValueError, "PUBLIC_TURN_SPEECH_ONLY"):
            continue_round_in_save(
                save,
                submission=PublicTurnActionSubmission(
                    actor_id=save.player_static_data.player_id,
                    action_text="I swing my sword anyway.",
                    speech_text="Not done yet.",
                    source_phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
                    forced_first=False,
                ),
                action_check=None,
                config=None,
            )

    def test_apply_public_turn_hp_damage_kills_non_team_npc_and_records_sub_zone(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_non_team_npc_death")
        guard = next(item for item in save.role_pool if item.role_id == "npc_guard")
        guard.profile.dnd5e_sheet.hit_points.current = 4

        hp_change, events = _apply_public_turn_hp_damage(
            save,
            source_actor_id=save.player_static_data.player_id,
            source_actor_name=save.player_static_data.name,
            target=ResolvedInteractionTarget(
                actor_id=guard.role_id,
                name=guard.name,
                actor_kind="npc",
                actor_type=PublicTurnActorType.NPC,
                role=guard,
            ),
            damage=6,
            damage_type="fire",
            round_id="ptround_non_team_down",
            phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
        )

        self.assertIsNotNone(hp_change)
        self.assertEqual(guard.profile.dnd5e_sheet.death_state.life_status, "dead")
        self.assertEqual(guard.profile.dnd5e_sheet.role_action_status, "dead")
        self.assertEqual(guard.state, "dead")
        dead_records = save.area_snapshot.sub_zones[0].state.dead_npc_records
        self.assertEqual([record.role_id for record in dead_records], ["npc_guard"])
        self.assertTrue(any(event.kind == "sub_zone_dead_npc_recorded" for event in events))
        visible_ids = {role.role_id for role in _visible_public_roles(save)}
        self.assertNotIn("npc_guard", visible_ids)

    def test_initiative_actor_rows_excludes_dead_role_even_if_player_mentions_it(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_dead_role_candidate")
        guard = next(item for item in save.role_pool if item.role_id == "npc_guard")
        guard.profile.dnd5e_sheet.is_dead = True
        guard.profile.dnd5e_sheet.role_action_status = "dead"
        guard.profile.dnd5e_sheet.death_state.life_status = "dead"
        guard.state = "dead"

        rows = initiative_actor_rows(
            save,
            player_text="瀹堝崼",
            addressed_role_name="瀹堝崼",
            config=None,
        )

        self.assertNotIn("npc_guard", [row["actor_id"] for row in rows])

    def test_attack_resolution_bundle_appends_death_summary_and_feeds_reactions(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_attack_death_summary")
        start_round_in_save(save, entry_type=PublicTurnEntryType.NEXT_ROUND, config=None)
        round_state = get_public_turn_state_in_save(save).current_round
        assert round_state is not None
        config = ChatConfig(
            provider="openai",
            api_key="test-key",
            model="test-model",
            stream=False,
            gm_prompt="gm",
        )
        guard = next(item for item in save.role_pool if item.role_id == "npc_guard")
        hit_target = PublicTurnResolvedAttackTarget(
            actor_id=guard.role_id,
            actor_name=guard.name,
            actor_type=PublicTurnActorType.NPC,
            role=guard,
        )
        captured_summary: list[str] = []

        def _capture_reactions(*args, **kwargs):
            captured_summary.append(str(kwargs.get("summary") or ""))
            return [], []

        with (
            patch(
                "app.services.public_turn_resolution._resolve_attack_damage_to_targets",
                return_value=(
                    [
                        {
                            "target_id": guard.role_id,
                            "target_name": guard.name,
                            "hp_before": 4,
                            "hp_after": 0,
                            "hp_delta": -4,
                        }
                    ],
                    [SimpleNamespace(event_id="damage_evt")],
                ),
            ),
            patch(
                "app.services.public_turn_resolution.generate_attack_outcome_narration",
                return_value=f"缪儿击中了{guard.name}。",
            ),
            patch("app.services.public_turn_resolution.apply_player_npc_reactions", side_effect=_capture_reactions),
        ):
            _, impact, settlement = _build_attack_resolution_bundle(
                save=save,
                session_id=save.session_id,
                round_state=round_state,
                actor_id=save.player_static_data.player_id,
                actor_name=save.player_static_data.name,
                actor_type="player",
                action_summary="斩击",
                speech_text="",
                action_result=None,
                attack_assessment={
                    "attack_kind": "targeted_attack",
                    "attack_basis": "weapon",
                    "attack_definition_id": "sword",
                    "attack_definition_name": "Sword",
                    "attack_area_shape": "none",
                },
                threatened_targets=[hit_target],
                hit_targets=[hit_target],
                avoided_targets=[],
                revealed_target_names=[],
                defense_action_text="",
                defense_speech_text="",
                base_events=[],
                config=config,
            )

        self.assertGreaterEqual(len(captured_summary), 1)
        self.assertIn("死亡", captured_summary[0])
        self.assertIn("死亡", settlement.gm_resolution_summary)
        self.assertTrue(any(change.hp_after == 0 for change in impact.hp_changes))

    def test_apply_public_turn_hp_damage_downs_team_npc_into_death_saving(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_team_npc_dying")
        bram = next(item for item in save.role_pool if item.role_id == "npc_bram")
        bram.profile.dnd5e_sheet.hit_points.current = 3

        hp_change, events = _apply_public_turn_hp_damage(
            save,
            source_actor_id="npc_guard",
            source_actor_name=next(item for item in save.role_pool if item.role_id == "npc_guard").name,
            target=ResolvedInteractionTarget(
                actor_id=bram.role_id,
                name=bram.name,
                actor_kind="npc",
                actor_type=PublicTurnActorType.NPC,
                role=bram,
            ),
            damage=5,
            damage_type="slashing",
            round_id="ptround_team_down",
            phase=PublicTurnPhase.NORMAL_ADVANCEMENT,
        )

        self.assertIsNotNone(hp_change)
        self.assertEqual(bram.profile.dnd5e_sheet.hit_points.current, 0)
        self.assertEqual(bram.profile.dnd5e_sheet.death_state.life_status, "dying")
        self.assertEqual(bram.profile.dnd5e_sheet.role_action_status, "death_saving")
        self.assertNotEqual(bram.state, "dead")
        self.assertEqual(save.area_snapshot.sub_zones[0].state.dead_npc_records, [])
        self.assertTrue(any(event.kind == "team_npc_entered_death_save" for event in events))

    def test_public_turn_embedded_failure_does_not_apply_generic_hp_penalty(self) -> None:
        save = self._seed_public_turn_scene("sess_public_turn_no_generic_failure_damage")
        hp_before = save.player_static_data.dnd5e_sheet.hit_points.current

        result = action_check(
            ActionCheckRequest(
                session_id=save.session_id,
                actor_role_id=save.player_static_data.player_id,
                action_type="attack",
                action_prompt="Launch a desperate spell that fizzles.",
                source_context="public_turn",
                resolution_context="embedded",
                planned_ability_used="intelligence",
                planned_dc=20,
                planned_time_spent_min=1,
                planned_requires_check=True,
                planned_check_task="cast the spell cleanly",
                forced_dice_roll=2,
                config=None,
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.applied_effects, [])
        self.assertEqual(save.player_static_data.dnd5e_sheet.hit_points.current, hp_before)

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
