import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.storage import storage_state
from app.models.schemas import (
    ActionCheckRequest,
    AreaNpc,
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    Coord3D,
    InventoryItem,
    NpcChatRequest,
    NpcRoleCard,
    EncounterCheckResponse,
    EncounterEntry,
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
)
from app.services.world_service import (
    action_check,
    add_player_buff,
    add_player_item,
    advance_public_scene_in_save,
    apply_public_npc_reactions_in_save,
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


VISIBLE_ACTION_TOKENS = ("看", "点头", "转过身", "肩", "眼神", "侧过脸", "手")


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

    def _seed_private_chat_role(self, session_id: str) -> None:
        save = clear_current_save(session_id)
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_chat",
                name="咔露",
                state="in_team",
                personality="谨慎寡言",
                speaking_style="说话简短直接",
                background="她一路都在追索旧地图上的遗失路线，也会留意沿途失落的传闻。",
                cognition="重视知识与传闻",
                likes=["旧地图", "地方传闻"],
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
                personality="谨慎",
                speaking_style="简短直接",
                profile=PlayerStaticData(role_type="npc"),
            ),
            NpcRoleCard(
                role_id="npc_bram",
                name="Bram",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                personality="警觉",
                speaking_style="低声回应",
                profile=PlayerStaticData(role_type="npc"),
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
                    name="短剑",
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
                    name="护盾术",
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
                name="测试NPC",
                profile=PlayerStaticData(role_type="npc"),
            )
        ]
        save_current(save)

        updated = set_role_relation(
            sid,
            "npc_x",
            RoleRelationSetRequest(target_role_id="player_001", relation_tag="friendly", note="测试"),
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
            player_text='{"input_type":"player_intent_v1","action_description":"我猛地推开木门","speech_description":"所有人都听着，我有话要说。"}',
            summary="GM summary",
        )
        save_current(loaded)

        self.assertIn("周围NPC反应", summary)
        updated = get_current_save(sid)
        role = updated.role_pool[0]
        self.assertTrue(any("公开记忆" in item for item in role.cognition_changes))
        self.assertTrue(any(item.kind == "public_npc_reaction" for item in updated.game_logs))

    def test_public_targeted_reply_stays_public_context_and_contains_visible_action(self) -> None:
        sid = "sess_public_targeted_reply"
        self._seed_public_scene_roles(sid)
        save = get_current_save(sid)

        events = advance_public_scene_in_save(
            save,
            session_id=sid,
            player_text='{"input_type":"player_intent_v1","speech_description":"Luna，你怎么看？"}',
            gm_summary="GM summary",
            config=None,
        )
        save_current(save)

        targeted = next(event for event in events if event.kind == "public_targeted_npc_reply")
        self.assertEqual(targeted.actor_role_id, "npc_luna")
        self.assertTrue(any(token in targeted.content for token in VISIBLE_ACTION_TOKENS))
        updated = get_current_save(sid)
        luna = next(item for item in updated.role_pool if item.role_id == "npc_luna")
        self.assertEqual(luna.dialogue_logs[-1].context_kind, "public_targeted")
        self.assertEqual(luna.dialogue_logs[-2].context_kind, "public_targeted")

    def test_public_bystander_reaction_contains_visible_action(self) -> None:
        sid = "sess_public_bystander_action"
        self._seed_public_scene_roles(sid)
        save = get_current_save(sid)

        events = advance_public_scene_in_save(
            save,
            session_id=sid,
            player_text='{"input_type":"player_intent_v1","action_description":"我在广场中央猛地挥了挥手","speech_description":"所有人先看这边"}',
            gm_summary="GM summary",
            config=None,
        )

        bystander = next(event for event in events if event.kind == "public_bystander_reaction")
        self.assertTrue(any(token in bystander.content for token in VISIBLE_ACTION_TOKENS))

    def test_action_check_narrative_does_not_inline_public_scene_summary(self) -> None:
        sid = "sess_action_check_no_inline_scene"
        self._seed_public_scene_roles(sid)

        result = action_check(
            ActionCheckRequest(
                session_id=sid,
                action_type="check",
                action_prompt='{"input_type":"player_intent_v1","action_description":"我朝广场中央挥手示意","speech_description":"Luna，看这边"}',
                forced_dice_roll=12,
                config=None,
            )
        )

        self.assertNotIn("【场景反应】", result.narrative)
        self.assertTrue(any(event.kind == "public_targeted_npc_reply" for event in result.scene_events))

    def test_encounter_started_event_contains_encounter_id(self) -> None:
        sid = "sess_public_scene_encounter_event"
        self._seed_public_scene_roles(sid)
        save = get_current_save(sid)
        fake_encounter = EncounterEntry(
            encounter_id="enc_meta",
            title="夜巷异响",
            description="一阵异样动静从巷口传来。",
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
                player_text='{"input_type":"player_intent_v1","action_description":"我突然在广场中央大声拍手","speech_description":"所有人先安静一下"}',
                gm_summary="GM summary",
                config=None,
            )

        started = next(event for event in events if event.kind == "encounter_started")
        self.assertEqual(started.metadata.get("encounter_id"), "enc_meta")
        self.assertEqual(started.metadata.get("encounter_title"), "夜巷异响")

    def test_npc_chat_fallback_answers_destination_question_with_specific_topic(self) -> None:
        sid = "sess_npc_chat_destination"
        self._seed_private_chat_role(sid)

        response = npc_chat(
            NpcChatRequest(
                session_id=sid,
                npc_role_id="npc_chat",
                player_message='{"input_type":"player_intent_v1","speech_description":"好吧，有什么想去的地方吗"}',
            )
        )

        self.assertTrue(any(token in response.action_reaction for token in VISIBLE_ACTION_TOKENS))
        self.assertTrue("旧地图" in response.speech_reply or "线索" in response.speech_reply)
        self.assertNotIn("我说的", response.speech_reply)
        self.assertNotIn("麻烦事", response.speech_reply)
        self.assertTrue(response.reply.startswith(response.action_reaction))

    def test_npc_chat_failed_action_still_answers_team_question(self) -> None:
        sid = "sess_npc_chat_team"
        self._seed_private_chat_role(sid)

        response = npc_chat(
            NpcChatRequest(
                session_id=sid,
                npc_role_id="npc_chat",
                player_message='{"input_type":"player_intent_v1","action_description":"轻轻踢了一脚你的屁股","speech_description":"你就是我的队友吗","action_check_result":{"success":false,"critical":"critical_failure"}}',
            )
        )

        self.assertTrue(any(token in response.action_reaction for token in VISIBLE_ACTION_TOKENS))
        self.assertTrue("队友" in response.speech_reply or "跟着你" in response.speech_reply)
        self.assertNotIn("你继续", response.speech_reply)
        self.assertNotIn("再继续谈", response.speech_reply)

    def test_npc_chat_conversation_state_tracks_and_explains_follow_up_topic(self) -> None:
        sid = "sess_npc_chat_follow_up"
        self._seed_private_chat_role(sid)

        first = npc_chat(
            NpcChatRequest(
                session_id=sid,
                npc_role_id="npc_chat",
                player_message='{"input_type":"player_intent_v1","speech_description":"那你有想去的地方吗"}',
            )
        )
        self.assertTrue("旧地图" in first.speech_reply or "线索" in first.speech_reply)

        second = npc_chat(
            NpcChatRequest(
                session_id=sid,
                npc_role_id="npc_chat",
                player_message='{"input_type":"player_intent_v1","speech_description":"什么旧地图？"}',
            )
        )

        self.assertIn("旧地图", second.speech_reply)
        self.assertTrue(any(token in second.speech_reply for token in ["我说的", "是这附近", "线索", "麻烦事"]))
        updated = get_current_save(sid)
        role = next(item for item in updated.role_pool if item.role_id == "npc_chat")
        self.assertEqual(role.conversation_state.current_topic, "旧地图")
        self.assertIn("什么旧地图", role.conversation_state.last_open_question)
        self.assertIn("旧地图", role.conversation_state.last_npc_claim)

    def test_npc_chat_log_content_does_not_repeat_speaker_name(self) -> None:
        sid = "sess_npc_chat_no_duplicate_name"
        self._seed_private_chat_role(sid)

        response = npc_chat(
            NpcChatRequest(
                session_id=sid,
                npc_role_id="npc_chat",
                player_message='{"input_type":"player_intent_v1","speech_description":"你就是我的队友吗"}',
            )
        )

        updated = get_current_save(sid)
        role = next(item for item in updated.role_pool if item.role_id == "npc_chat")
        self.assertFalse(response.action_reaction.startswith(role.name))
        self.assertFalse(role.dialogue_logs[-1].content.startswith(role.name))


if __name__ == "__main__":
    unittest.main()
