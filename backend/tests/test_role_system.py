import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.prompt_table import prompt_table
from app.core.storage import storage_state
from app.models.schemas import (
    ActionCheckRequest,
    ActionCheckPlanRequest,
    AreaNpc,
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    ChatConfig,
    Coord3D,
    EncounterCheckResponse,
    EncounterEntry,
    EncounterTerminationCondition,
    InventoryItem,
    NpcChatRequest,
    NpcRoleCard,
    PlayerBuffAddRequest,
    PlayerEquipRequest,
    PlayerItemAddRequest,
    PlayerRuntimeData,
    PlayerSpellSlotAdjustRequest,
    PlayerStaminaAdjustRequest,
    PlayerStaticData,
    Position,
    RoleBuff,
    RoleRelationSetRequest,
    SubZoneChatTurn,
    TeamMember,
)
from app.services.team_service import ensure_team_state
from app.services.world_service import (
    _parse_player_intent,
    NpcChatConfigError,
    NpcChatGenerationError,
    action_check,
    plan_action_check,
    add_player_buff,
    add_player_item,
    advance_public_scene_in_save,
    apply_speech_time,
    apply_public_npc_reactions_in_save,
    build_main_turn_context_payload,
    clear_current_save,
    consume_spell_slots,
    consume_stamina,
    equip_player_item,
    get_current_save,
    npc_chat,
    recover_spell_slots,
    recover_stamina,
    save_current,
    set_role_relation,
)


class RoleSystemTests(unittest.TestCase):
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

    def _chat_config(self) -> ChatConfig:
        return ChatConfig(openai_api_key="test-key", model="test-model", stream=False, gm_prompt="gm")

    def _fake_openai_client(self, content: str):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response)))

    def _seed_private_chat_role(self, session_id: str) -> None:
        save = clear_current_save(session_id)
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_chat",
                name="KaLu",
                state="in_team",
                personality="careful",
                speaking_style="short answers",
                background="She has been tracing clues from an old map.",
                cognition="values concrete knowledge",
                likes=["old map", "local rumors"],
                profile=PlayerStaticData(role_type="npc"),
            )
        ]
        save_current(save)

    def _seed_public_scene_roles(self, session_id: str) -> None:
        save = clear_current_save(session_id)
        save.area_snapshot = AreaSnapshot(
            zones=[AreaZone(zone_id="zone_square", name="Square", center=Coord3D(x=0, y=0, z=0), sub_zone_ids=["sub_square_1"])],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_square_1",
                    zone_id="zone_square",
                    name="Center",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="Open square",
                    npcs=[
                        AreaNpc(npc_id="npc_luna", name="Luna", state="idle"),
                        AreaNpc(npc_id="npc_bram", name="Bram", state="idle"),
                    ],
                )
            ],
            current_zone_id="zone_square",
            current_sub_zone_id="sub_square_1",
            clock=save.area_snapshot.clock,
        )
        save.map_snapshot.player_position = Position(x=0, y=0, z=0, zone_id="zone_square")
        save.player_runtime_data = PlayerRuntimeData(
            session_id=session_id,
            current_position=Position(x=0, y=0, z=0, zone_id="zone_square"),
        )
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_luna",
                name="Luna",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                personality="careful",
                speaking_style="direct",
                profile=PlayerStaticData(role_type="npc"),
            ),
            NpcRoleCard(
                role_id="npc_bram",
                name="Bram",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                personality="alert",
                speaking_style="low voice",
                profile=PlayerStaticData(role_type="npc"),
            ),
        ]
        save_current(save)

    def _seed_scene_context_with_team_and_encounter(self, session_id: str) -> None:
        self._seed_public_scene_roles(session_id)
        save = get_current_save(session_id)
        save.area_snapshot.sub_zones[0].chat_context.recent_turns.append(
            SubZoneChatTurn(
                turn_id="turn_1",
                world_time_text="Day 1 09:00",
                player_action="Player checks the square.",
                player_speech="Everyone stay quiet.",
                gm_narration="The square grows tense.",
            )
        )
        save.encounter_state.encounters = [
            EncounterEntry(
                encounter_id="enc_square",
                type="npc",
                status="active",
                title="Square Trouble",
                description="A disturbance breaks out in the square.",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                player_presence="engaged",
                npc_role_id="npc_luna",
                scene_summary="The square is tense.",
                latest_outcome_summary="Something is about to happen.",
                termination_conditions=[
                    EncounterTerminationCondition(
                        condition_id="cond_goal",
                        kind="target_resolved",
                        description="Resolve the disturbance.",
                    )
                ],
            )
        ]
        save.encounter_state.active_encounter_id = "enc_square"
        save.role_pool.append(
            NpcRoleCard(
                role_id="npc_iris",
                name="Iris",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                personality="steady",
                speaking_style="measured",
                profile=PlayerStaticData(role_type="npc"),
            )
        )
        team_state = ensure_team_state(save)
        team_state.members = [
            TeamMember(
                role_id="npc_bram",
                name="Bram",
                origin_zone_id="zone_square",
                origin_sub_zone_id="sub_square_1",
            ),
            TeamMember(
                role_id="npc_iris",
                name="Iris",
                origin_zone_id="zone_square",
                origin_sub_zone_id="sub_square_1",
            ),
        ]
        save_current(save)

    def test_item_equip_and_buff_recompute(self) -> None:
        sid = "sess_role_item"
        save = clear_current_save(sid)
        base_ac = save.player_static_data.dnd5e_sheet.armor_class

        updated = add_player_item(
            sid,
            PlayerItemAddRequest(
                item=InventoryItem(
                    item_id="sword_1",
                    name="Short Sword",
                    slot_type="weapon",
                    attack_bonus=2,
                )
            ),
        )
        self.assertEqual(len(updated.dnd5e_sheet.backpack.items), 1)

        updated = equip_player_item(sid, PlayerEquipRequest(item_id="sword_1", slot="weapon"))
        self.assertEqual(updated.dnd5e_sheet.equipment_slots.weapon_item_id, "sword_1")

        updated = add_player_buff(
            sid,
            PlayerBuffAddRequest(
                buff=RoleBuff(
                    buff_id="buff_ac",
                    name="Shielded",
                    effect={"ac_delta": 2, "dc_delta": 1},
                )
            ),
        )
        self.assertGreaterEqual(updated.dnd5e_sheet.armor_class, base_ac + 2)
        self.assertGreaterEqual(updated.dnd5e_sheet.difficulty_class, 1)

    def test_spell_slots_and_stamina_consume_recover(self) -> None:
        sid = "sess_role_resource"
        clear_current_save(sid)
        updated = consume_spell_slots(sid, PlayerSpellSlotAdjustRequest(level=1, amount=1))
        self.assertEqual(updated.dnd5e_sheet.spell_slots_current.level_1, 1)
        updated = recover_spell_slots(sid, PlayerSpellSlotAdjustRequest(level=1, amount=1))
        self.assertEqual(updated.dnd5e_sheet.spell_slots_current.level_1, 2)

        updated = consume_stamina(sid, PlayerStaminaAdjustRequest(amount=3))
        self.assertEqual(updated.dnd5e_sheet.stamina_current, 7)
        updated = recover_stamina(sid, PlayerStaminaAdjustRequest(amount=2))
        self.assertEqual(updated.dnd5e_sheet.stamina_current, 9)

    def test_set_role_relation(self) -> None:
        sid = "sess_role_relation"
        save = clear_current_save(sid)
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_x",
                name="Test NPC",
                profile=PlayerStaticData(role_type="npc"),
            )
        ]
        save_current(save)

        updated = set_role_relation(
            sid,
            "npc_x",
            RoleRelationSetRequest(target_role_id="player_001", relation_tag="friendly", note="test"),
        )
        self.assertEqual(updated.relations[-1].target_role_id, "player_001")
        self.assertEqual(updated.relations[-1].relation_tag, "friendly")
        persisted = get_current_save(sid)
        self.assertEqual(persisted.role_pool[0].relations[-1].relation_tag, "friendly")

    def test_load_fills_missing_npc_profile_fields(self) -> None:
        sid = "sess_role_complete"
        save = clear_current_save(sid)
        save.area_snapshot = AreaSnapshot(
            zones=[AreaZone(zone_id="zone_role", name="Role Town", center=Coord3D(x=0, y=0, z=0), sub_zone_ids=["sub_role_1"])],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_role_1",
                    zone_id="zone_role",
                    name="Market",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="Bustling market",
                    npcs=[AreaNpc(npc_id="npc_gap", name="Gap NPC", state="idle")],
                )
            ],
            current_zone_id="zone_role",
            current_sub_zone_id="sub_role_1",
            clock=save.area_snapshot.clock,
        )
        save.map_snapshot.player_position = Position(x=0, y=0, z=0, zone_id="zone_role")
        save.role_pool = [NpcRoleCard(role_id="npc_gap", name="Gap NPC", zone_id="zone_role", sub_zone_id="sub_role_1", profile=PlayerStaticData(role_type="npc"))]
        save_current(save)

        updated = get_current_save(sid)
        role = next(item for item in updated.role_pool if item.role_id == "npc_gap")
        self.assertTrue(role.secret)
        self.assertTrue(role.likes)
        self.assertGreater(role.talkative_maximum, 0)
        self.assertGreaterEqual(role.talkative_current, 0)
        self.assertTrue(role.profile.dnd5e_sheet.race)
        self.assertTrue(role.profile.dnd5e_sheet.char_class)
        self.assertTrue(role.profile.dnd5e_sheet.background)
        self.assertTrue(role.profile.dnd5e_sheet.languages)
        self.assertTrue(role.profile.dnd5e_sheet.skills_proficient)
        self.assertTrue(role.profile.dnd5e_sheet.tool_proficiencies)
        self.assertTrue(role.profile.dnd5e_sheet.features_traits)
        self.assertGreaterEqual(len(role.profile.dnd5e_sheet.backpack.items), 2)
        self.assertIsNotNone(role.profile.dnd5e_sheet.equipment_slots.weapon_item_id)
        self.assertIsNotNone(role.profile.dnd5e_sheet.equipment_slots.armor_item_id)

    def test_public_npc_reaction_updates_memory(self) -> None:
        sid = "sess_public_npc_memory"
        save = clear_current_save(sid)
        save.area_snapshot = AreaSnapshot(
            zones=[AreaZone(zone_id="zone_square", name="Square", center=Coord3D(x=0, y=0, z=0), sub_zone_ids=["sub_square_1"])],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_square_1",
                    zone_id="zone_square",
                    name="Center",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="Open square",
                    npcs=[AreaNpc(npc_id="npc_square", name="Square Watcher", state="idle")],
                )
            ],
            current_zone_id="zone_square",
            current_sub_zone_id="sub_square_1",
            clock=save.area_snapshot.clock,
        )
        save.map_snapshot.player_position = Position(x=0, y=0, z=0, zone_id="zone_square")
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_square",
                name="Square Watcher",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                profile=PlayerStaticData(role_type="npc"),
            )
        ]
        save_current(save)

        loaded = get_current_save(sid)
        summary = apply_public_npc_reactions_in_save(
            loaded,
            session_id=sid,
            player_text='{"input_type":"player_intent_v1","action_description":"I shove the old gate","speech_description":"Everyone listen to me."}',
            summary="GM summary",
        )
        save_current(loaded)

        self.assertIn("NPC", summary)
        updated = get_current_save(sid)
        role = updated.role_pool[0]
        self.assertTrue(any("公开记忆" in item for item in role.cognition_changes))
        self.assertTrue(any(item.kind == "public_npc_reaction" for item in updated.game_logs))

    def test_public_targeted_reply_stays_public_context(self) -> None:
        sid = "sess_public_targeted_reply"
        self._seed_public_scene_roles(sid)
        save = get_current_save(sid)

        events = advance_public_scene_in_save(
            save,
            session_id=sid,
            player_text='{"input_type":"player_intent_v1","speech_description":"Luna, what do you think?"}',
            gm_summary="GM summary",
            config=None,
        )
        save_current(save)

        targeted = next(event for event in events if event.kind == "public_targeted_npc_reply")
        self.assertEqual(targeted.actor_role_id, "npc_luna")
        self.assertTrue(targeted.content)
        updated = get_current_save(sid)
        luna = next(item for item in updated.role_pool if item.role_id == "npc_luna")
        self.assertEqual(luna.dialogue_logs[-1].context_kind, "public_targeted")
        self.assertEqual(luna.dialogue_logs[-2].context_kind, "public_targeted")

    def test_public_bystander_reaction_is_written_with_public_reaction_context(self) -> None:
        sid = "sess_public_bystander_memory"
        self._seed_public_scene_roles(sid)
        save = get_current_save(sid)

        events = advance_public_scene_in_save(
            save,
            session_id=sid,
            player_text='{"input_type":"player_intent_v1","action_description":"I wave in the square","speech_description":"Everyone look over here"}',
            gm_summary="GM summary",
            config=None,
        )
        save_current(save)

        self.assertTrue(any(event.kind == "public_bystander_reaction" for event in events))
        updated = get_current_save(sid)
        bram = next(item for item in updated.role_pool if item.role_id == "npc_bram")
        self.assertEqual(bram.dialogue_logs[-1].context_kind, "public_reaction")

    def test_encounter_scene_bystander_reaction_is_written_with_encounter_context(self) -> None:
        sid = "sess_encounter_bystander_memory"
        self._seed_scene_context_with_team_and_encounter(sid)
        save = get_current_save(sid)

        events = advance_public_scene_in_save(
            save,
            session_id=sid,
            player_text='{"input_type":"player_intent_v1","action_description":"I step toward the noise","speech_description":"Luna, answer me now"}',
            gm_summary="The square tightens around the active encounter.",
            config=None,
        )
        save_current(save)

        self.assertTrue(any(event.actor_role_id == "npc_bram" and event.kind in {"team_public_reaction", "public_actor_resolution"} for event in events))
        updated = get_current_save(sid)
        bram = next(item for item in updated.role_pool if item.role_id == "npc_bram")
        self.assertEqual(bram.dialogue_logs[-1].context_kind, "encounter")

    def test_action_check_narrative_does_not_inline_public_scene_summary(self) -> None:
        sid = "sess_action_check_no_inline_scene"
        self._seed_public_scene_roles(sid)

        result = action_check(
            ActionCheckRequest(
                session_id=sid,
                action_type="check",
                action_prompt='{"input_type":"player_intent_v1","action_description":"I signal toward the square","speech_description":"Luna, look here"}',
                forced_dice_roll=12,
                config=None,
            )
        )

        self.assertNotIn("场景反应", result.narrative)
        self.assertTrue(any(event.kind == "public_targeted_npc_reply" for event in result.scene_events))

    def test_plan_action_check_returns_check_task_and_modifier(self) -> None:
        sid = "sess_action_check_plan"
        clear_current_save(sid)

        result = plan_action_check(
            ActionCheckPlanRequest(
                session_id=sid,
                action_type="check",
                action_prompt="我尝试说服守卫让我进门",
                actor_role_id="player_001",
                config=None,
            )
        )

        self.assertEqual(result.actor_role_id, "player_001")
        self.assertEqual(result.actor_kind, "player")
        self.assertTrue(result.check_task)
        self.assertIsInstance(result.ability_modifier, int)

    def test_action_check_player_requires_roll_when_check_needed(self) -> None:
        sid = "sess_action_check_player_roll_required"
        clear_current_save(sid)

        with self.assertRaisesRegex(ValueError, "PLAYER_DICE_ROLL_REQUIRED"):
            action_check(
                ActionCheckRequest(
                    session_id=sid,
                    action_type="check",
                    action_prompt="我尝试强行撬开上锁的门",
                    planned_ability_used="dexterity",
                    planned_dc=14,
                    planned_time_spent_min=2,
                    planned_requires_check=True,
                    planned_check_task="撬开上锁的门",
                    resolution_context="embedded",
                )
            )

    def test_action_check_npc_can_auto_roll_without_forced_dice(self) -> None:
        sid = "sess_action_check_npc_auto_roll"
        save = clear_current_save(sid)
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_auto",
                name="Auto NPC",
                profile=PlayerStaticData(role_type="npc"),
            )
        ]
        save_current(save)

        result = action_check(
            ActionCheckRequest(
                session_id=sid,
                actor_role_id="npc_auto",
                action_type="check",
                action_prompt="NPC 尝试翻过矮墙",
                planned_ability_used="dexterity",
                planned_dc=12,
                planned_time_spent_min=2,
                planned_requires_check=True,
                planned_check_task="翻过矮墙",
                resolution_context="embedded",
            )
        )

        self.assertEqual(result.actor_kind, "npc")
        self.assertIsNotNone(result.dice_roll)
        self.assertEqual(result.check_task, "翻过矮墙")

    def test_action_check_embedded_keeps_scene_events_empty(self) -> None:
        sid = "sess_action_check_embedded_no_scene"
        self._seed_public_scene_roles(sid)

        result = action_check(
            ActionCheckRequest(
                session_id=sid,
                action_type="check",
                action_prompt='{"input_type":"player_intent_v1","action_description":"I test the gate","speech_description":"Hold the line"}',
                forced_dice_roll=12,
                planned_ability_used="strength",
                planned_dc=10,
                planned_time_spent_min=2,
                planned_requires_check=True,
                planned_check_task="推开大门",
                resolution_context="embedded",
            )
        )

        self.assertEqual(result.scene_events, [])
        self.assertIn("【检定】", result.narrative)

    def test_encounter_started_event_contains_encounter_id(self) -> None:
        sid = "sess_public_scene_encounter_event"
        self._seed_public_scene_roles(sid)
        save = get_current_save(sid)
        fake_encounter = EncounterEntry(
            encounter_id="enc_meta",
            title="Night Noise",
            description="Something strange echoes from the alley.",
            status="queued",
            trigger_kind="random_dialog",
        )

        with patch(
            "app.services.encounter_service.check_for_encounter",
            return_value=EncounterCheckResponse(generated=True, encounter_id="enc_meta", encounter=fake_encounter),
        ):
            events = advance_public_scene_in_save(
                save,
                session_id=sid,
                player_text='{"input_type":"player_intent_v1","action_description":"I clap loudly in the square","speech_description":"Everyone be quiet"}',
                gm_summary="GM summary",
                config=None,
            )

        started = next(event for event in events if event.kind == "encounter_started")
        self.assertEqual(started.metadata.get("encounter_id"), "enc_meta")
        self.assertEqual(started.metadata.get("encounter_title"), "Night Noise")

    def test_public_scene_prompts_receive_active_encounter_and_recent_turns(self) -> None:
        sid = "sess_scene_prompt_context"
        self._seed_scene_context_with_team_and_encounter(sid)
        save = get_current_save(sid)
        config = self._chat_config()
        npc_client = self._fake_openai_client('{"action_reaction":"He glances over.","speech_reply":"I heard it too.","relation_tag":"friendly"}')
        team_client = self._fake_openai_client('{"action_reaction":"He squares his shoulders.","speech_reply":"I am with you.","affinity_delta":1,"trust_delta":1}')

        with patch("app.services.world_service.create_sync_client", return_value=npc_client):
            with patch("app.services.team_service.create_sync_client", return_value=team_client):
                with patch("app.core.prompt_table.prompt_table.render", wraps=prompt_table.render) as mocked_render:
                    advance_public_scene_in_save(
                        save,
                        session_id=sid,
                        player_text='{"input_type":"player_intent_v1","action_description":"I move toward the disturbance","speech_description":"Luna, what do you see?"}',
                        gm_summary="The encounter is unfolding in the square.",
                        config=config,
                    )

        captured: dict[str, dict[str, object]] = {}
        for call in mocked_render.call_args_list:
            if not call.args:
                continue
            key = call.args[0]
            if key == "scene.actor.intent.user.v1":
                captured[key] = call.kwargs

        for key in ("scene.actor.intent.user.v1",):
            self.assertIn(key, captured)
            scene_context = json.loads(str(captured[key]["scene_context_json"]))
            self.assertEqual(scene_context["active_encounter"]["encounter_id"], "enc_square")
            self.assertTrue(scene_context["sub_zone_recent_turns"])

    def test_npc_chat_requires_config_for_ai_generation(self) -> None:
        sid = "sess_npc_chat_requires_config"
        self._seed_private_chat_role(sid)

        with self.assertRaises(NpcChatConfigError):
            npc_chat(
                NpcChatRequest(
                    session_id=sid,
                    npc_role_id="npc_chat",
                    player_message='{"input_type":"player_intent_v1","speech_description":"Tell me what you know."}',
                )
            )

    def test_npc_chat_invalid_model_output_raises_generation_error(self) -> None:
        sid = "sess_npc_chat_bad_json"
        self._seed_private_chat_role(sid)

        with patch("app.services.world_service.create_sync_client", return_value=self._fake_openai_client("not-json")):
            with self.assertRaises(NpcChatGenerationError):
                npc_chat(
                    NpcChatRequest(
                        session_id=sid,
                        npc_role_id="npc_chat",
                        player_message='{"input_type":"player_intent_v1","speech_description":"Tell me something useful."}',
                        config=self._chat_config(),
                    )
                )

    def test_npc_chat_forbidden_entity_raises_generation_error(self) -> None:
        sid = "sess_npc_chat_forbidden_entity"
        self._seed_private_chat_role(sid)
        save = get_current_save(sid)
        save.role_pool.append(
            NpcRoleCard(
                role_id="npc_hidden",
                name="ForbiddenName",
                profile=PlayerStaticData(role_type="npc"),
            )
        )
        save_current(save)

        with patch(
            "app.services.world_service.create_sync_client",
            return_value=self._fake_openai_client(
                '{"action_reaction":"She leans in slightly.","speech_reply":"Go ask ForbiddenName instead.","relation_tag":"neutral"}'
            ),
        ):
            with patch(
                "app.services.world_service.build_npc_knowledge_snapshot",
                return_value=SimpleNamespace(
                    response_rules=["stay in bounds"],
                    known_local_npc_ids=["npc_chat"],
                    forbidden_entity_ids=["npc_hidden"],
                ),
            ):
                with self.assertRaises(NpcChatGenerationError):
                    npc_chat(
                        NpcChatRequest(
                            session_id=sid,
                            npc_role_id="npc_chat",
                            player_message='{"input_type":"player_intent_v1","speech_description":"Who should I ask?"}',
                            config=self._chat_config(),
                        )
                    )

    def test_npc_chat_conversation_state_tracks_follow_up_topic(self) -> None:
        sid = "sess_npc_chat_follow_up"
        self._seed_private_chat_role(sid)
        responses = [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"action_reaction":"她指尖在桌面上轻敲了一下。","speech_reply":"我说的旧地图是前些年留下的那一张。","relation_tag":"met"}'))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"action_reaction":"她抬眼看了你一瞬。","speech_reply":"旧地图上标着一条被封掉的小路。","relation_tag":"met"}'))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            ),
        ]
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: responses.pop(0))))

        with patch("app.services.world_service.create_sync_client", return_value=fake_client):
            first = npc_chat(
                NpcChatRequest(
                    session_id=sid,
                    npc_role_id="npc_chat",
                    player_message='{"input_type":"player_intent_v1","speech_description":"你说的旧地图是什么意思？"}',
                    config=self._chat_config(),
                )
            )
            second = npc_chat(
                NpcChatRequest(
                    session_id=sid,
                    npc_role_id="npc_chat",
                    player_message='{"input_type":"player_intent_v1","speech_description":"那旧地图上到底写了什么？"}',
                    config=self._chat_config(),
                )
            )

        self.assertIn("旧地图", first.speech_reply)
        self.assertIn("旧地图", second.speech_reply)
        updated = get_current_save(sid)
        role = next(item for item in updated.role_pool if item.role_id == "npc_chat")
        self.assertIn("旧地图", role.conversation_state.current_topic)
        self.assertIn("旧地图", role.conversation_state.last_open_question)
        self.assertIn("旧地图", role.conversation_state.last_npc_claim)

    def test_npc_chat_log_content_does_not_repeat_speaker_name(self) -> None:
        sid = "sess_npc_chat_no_duplicate_name"
        self._seed_private_chat_role(sid)

        with patch(
            "app.services.world_service.create_sync_client",
            return_value=self._fake_openai_client(
                '{"action_reaction":"KaLu just raises her eyes for a second.","speech_reply":"I am your teammate.","relation_tag":"friendly"}'
            ),
        ):
            response = npc_chat(
                NpcChatRequest(
                    session_id=sid,
                    npc_role_id="npc_chat",
                    player_message='{"input_type":"player_intent_v1","speech_description":"Are you my teammate?"}',
                    config=self._chat_config(),
                )
            )

        updated = get_current_save(sid)
        role = next(item for item in updated.role_pool if item.role_id == "npc_chat")
        self.assertFalse(response.action_reaction.startswith(role.name))
        self.assertFalse(role.dialogue_logs[-1].content.startswith(role.name))

    def test_sub_zone_context_persists_and_feeds_main_turn_context(self) -> None:
        sid = "sess_sub_zone_context_persist"
        self._seed_public_scene_roles(sid)
        save = get_current_save(sid)
        save.area_snapshot.sub_zones[0].chat_context.recent_turns.extend(
            [
                SubZoneChatTurn(
                    turn_id="turn_a",
                    world_time_text="Day 1 09:00",
                    player_action="I check the square gate.",
                    player_speech="Stay alert.",
                    gm_narration="The square falls quiet.",
                ),
                SubZoneChatTurn(
                    turn_id="turn_b",
                    world_time_text="Day 1 09:10",
                    player_action="I step closer.",
                    player_speech="What moved there?",
                    gm_narration="A shadow crosses the stones.",
                ),
            ]
        )
        save_current(save)

        reloaded = get_current_save(sid)
        self.assertEqual(len(reloaded.area_snapshot.sub_zones[0].chat_context.recent_turns), 2)

        payload = build_main_turn_context_payload(
            reloaded,
            '{"input_type":"player_intent_v1","action_description":"I draw steel","speech_description":"Show yourself."}',
        )
        self.assertEqual(len(payload["sub_zone_recent_turns"]), 2)
        self.assertEqual(payload["sub_zone_recent_turns"][0]["world_time_text"], "Day 1 09:00")

    def test_passive_turn_intent_uses_fixed_display_text(self) -> None:
        parsed = _parse_player_intent('{"input_type":"player_intent_v1","passive_turn":true,"passive_mode":"observe"}')

        self.assertTrue(parsed["passive_turn"])
        self.assertEqual(parsed["passive_mode"], "observe")
        self.assertEqual(parsed["display_text"], "【自动推进】玩家本轮选择观察与等待，不主动行动。")
        self.assertEqual(parsed["action_text"], "")
        self.assertEqual(parsed["speech_text"], "")

    def test_apply_speech_time_uses_one_minute_for_passive_turn(self) -> None:
        sid = "sess_passive_turn_time"
        clear_current_save(sid)

        spent = apply_speech_time(sid, '{"input_type":"player_intent_v1","passive_turn":true,"passive_mode":"observe"}', None)

        self.assertEqual(spent, 1)
        save = get_current_save(sid)
        self.assertEqual(save.game_logs[-1].kind, "speech_time")
        self.assertEqual(save.game_logs[-1].payload.get("time_spent_min"), 1)

    def test_main_turn_context_includes_passive_input_and_player_mode(self) -> None:
        sid = "sess_passive_turn_context"
        self._seed_public_scene_roles(sid)
        save = get_current_save(sid)
        save.area_snapshot.sub_zones[0].chat_context.recent_turns.append(
            SubZoneChatTurn(
                turn_id="turn_passive",
                player_mode="passive",
                world_time_text="Day 1 09:20",
                player_action="",
                player_speech="",
                gm_narration="The square shifts while the player watches.",
            )
        )
        save_current(save)

        payload = build_main_turn_context_payload(
            get_current_save(sid),
            '{"input_type":"player_intent_v1","passive_turn":true,"passive_mode":"observe"}',
        )

        self.assertTrue(payload["player_input"]["passive_turn"])
        self.assertEqual(payload["player_input"]["passive_mode"], "observe")
        self.assertEqual(payload["sub_zone_recent_turns"][0]["player_mode"], "passive")


if __name__ == "__main__":
    unittest.main()
