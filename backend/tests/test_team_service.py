import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.storage import _save_bundle_dir, read_json, storage_state
from app.models.schemas import (
    AreaNpc,
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    ChatConfig,
    Coord3D,
    NpcRoleCard,
    PlayerStaticData,
    TeamChatRequest,
    TeamDebugGenerateRequest,
    TeamInviteRequest,
    TeamLeaveRequest,
)
from app.services.team_service import (
    apply_team_reactions,
    generate_debug_teammate,
    generate_team_public_replies_in_save,
    invite_npc_to_team,
    leave_npc_from_team,
    team_chat,
)
from app.services.world_service import clear_current_save, get_current_save, save_current


class TeamServiceTests(unittest.TestCase):
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

    def _seed_context(self, session_id: str) -> None:
        save = clear_current_save(session_id)
        save.area_snapshot = AreaSnapshot(
            zones=[
                AreaZone(
                    zone_id="zone_town",
                    name="Town",
                    center=Coord3D(x=0, y=0, z=0),
                    sub_zone_ids=["sub_zone_town_1"],
                )
            ],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_zone_town_1",
                    zone_id="zone_town",
                    name="Guild Hall",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="Guild hall",
                    npcs=[AreaNpc(npc_id="npc_local", name="Local Clerk", state="idle")],
                )
            ],
            current_zone_id="zone_town",
            current_sub_zone_id="sub_zone_town_1",
            clock=save.area_snapshot.clock,
        )
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_local",
                name="Local Clerk",
                zone_id="zone_town",
                sub_zone_id="sub_zone_town_1",
                profile=PlayerStaticData(role_type="npc"),
                relations=[],
            )
        ]
        save_current(save)

    def test_save_bundle_contains_team_state_part(self) -> None:
        sid = "sess_team_bundle"
        save = clear_current_save(sid)
        save_current(save)

        bundle_dir = _save_bundle_dir(storage_state.save_path)
        manifest = read_json(bundle_dir / "manifest.json")
        parts = manifest.get("parts", {})

        self.assertIn("team_state", parts)
        self.assertTrue((bundle_dir / "team_state.json").exists())

    def test_invite_npc_to_team_marks_role_in_team(self) -> None:
        sid = "sess_team_invite"
        self._seed_context(sid)

        response = invite_npc_to_team(TeamInviteRequest(session_id=sid, npc_role_id="npc_local", player_prompt="一起行动吧。"))
        self.assertTrue(response.accepted)
        self.assertIsNotNone(response.member)

        updated = get_current_save(sid)
        self.assertEqual(len(updated.team_state.members), 1)
        self.assertEqual(updated.team_state.members[0].role_id, "npc_local")
        self.assertEqual(updated.role_pool[0].state, "in_team")
        self.assertFalse(any(item.npc_id == "npc_local" for item in updated.area_snapshot.sub_zones[0].npcs))

    def test_debug_teammate_removed_when_leaving(self) -> None:
        sid = "sess_debug_teammate"
        self._seed_context(sid)

        created = generate_debug_teammate(TeamDebugGenerateRequest(session_id=sid, prompt="沉默的斥候"))
        self.assertIsNotNone(created.member)
        role_id = created.member.role_id if created.member is not None else ""

        left = leave_npc_from_team(TeamLeaveRequest(session_id=sid, npc_role_id=role_id, reason="manual"))
        self.assertEqual(left.team_state.members, [])

        updated = get_current_save(sid)
        self.assertFalse(any(item.role_id == role_id for item in updated.role_pool))
        self.assertEqual(updated.team_state.members, [])

    def test_debug_teammate_has_complete_profile(self) -> None:
        sid = "sess_debug_teammate_profile"
        self._seed_context(sid)

        created = generate_debug_teammate(TeamDebugGenerateRequest(session_id=sid, prompt="debug scout"))
        self.assertIsNotNone(created.role)
        assert created.role is not None
        role = created.role

        self.assertTrue(role.secret)
        self.assertTrue(role.likes)
        self.assertGreater(role.talkative_maximum, 0)
        self.assertTrue(role.profile.dnd5e_sheet.race)
        self.assertTrue(role.profile.dnd5e_sheet.char_class)
        self.assertTrue(role.profile.dnd5e_sheet.languages)
        self.assertTrue(role.profile.dnd5e_sheet.features_traits)
        self.assertGreaterEqual(len(role.profile.dnd5e_sheet.backpack.items), 2)
        self.assertIsNotNone(role.profile.dnd5e_sheet.equipment_slots.weapon_item_id)
        self.assertIsNotNone(role.profile.dnd5e_sheet.equipment_slots.armor_item_id)

    def test_debug_teammate_prompt_shapes_role_fields(self) -> None:
        sid = "sess_debug_teammate_ai_shape"
        self._seed_context(sid)
        config = ChatConfig(
            openai_api_key="test-key",
            model="test-model",
            stream=False,
            gm_prompt="gm",
        )
        ai_spec = {
            "display_name": "艾岚",
            "race": "精灵",
            "char_class": "游侠",
            "sheet_background": "边境猎手",
            "alignment": "neutral_good",
            "personality": "寡言",
            "speaking_style": "说话低声而克制",
            "appearance": "背着短弓，披着旧斗篷",
            "background": "她长期追踪边境旧路。",
            "cognition": "重视知识与传闻",
            "secret": "藏着一份旧地图副本。",
            "likes": ["旧地图", "安静的夜晚"],
            "languages": ["精灵语"],
            "tool_proficiencies": ["猎具维护包"],
            "skills_proficient": ["survival", "perception"],
            "features_traits": ["追踪者"],
            "spells": ["猎人印记"],
            "preferred_weapon": "短弓",
            "preferred_armor": "皮甲",
            "inventory_items": ["旧地图", "草药袋"],
            "notes": "擅长远程侦察。",
            "ability_bias": "dexterity",
        }

        with patch("app.services.team_service._ai_team_role_spec", return_value=ai_spec):
            created = generate_debug_teammate(
                TeamDebugGenerateRequest(session_id=sid, prompt="精灵游侠，擅长短弓和旧地图。", config=config)
            )

        self.assertIsNotNone(created.role)
        assert created.role is not None
        role = created.role
        self.assertEqual(role.profile.dnd5e_sheet.race, "精灵")
        self.assertEqual(role.profile.dnd5e_sheet.char_class, "游侠")
        self.assertIn("旧地图", role.likes)
        self.assertIn("精灵语", role.profile.dnd5e_sheet.languages)
        self.assertIn("猎人印记", role.profile.dnd5e_sheet.spells)
        weapon_id = role.profile.dnd5e_sheet.equipment_slots.weapon_item_id
        weapon = next(item for item in role.profile.dnd5e_sheet.backpack.items if item.item_id == weapon_id)
        self.assertEqual(weapon.name, "短弓")

    def test_debug_teammate_fallback_parses_prompt_without_ai(self) -> None:
        sid = "sess_debug_teammate_fallback"
        self._seed_context(sid)

        created = generate_debug_teammate(
            TeamDebugGenerateRequest(session_id=sid, prompt="精灵游侠，善用短弓，懂精灵语，喜欢旧地图，寡言")
        )

        self.assertIsNotNone(created.role)
        assert created.role is not None
        role = created.role
        self.assertEqual(role.profile.dnd5e_sheet.race, "精灵")
        self.assertEqual(role.profile.dnd5e_sheet.char_class, "游侠")
        self.assertIn("旧地图", role.likes)
        self.assertIn("精灵语", role.profile.dnd5e_sheet.languages)
        self.assertIn("寡言", role.personality)
        weapon_id = role.profile.dnd5e_sheet.equipment_slots.weapon_item_id
        weapon = next(item for item in role.profile.dnd5e_sheet.backpack.items if item.item_id == weapon_id)
        self.assertEqual(weapon.name, "短弓")

    def test_negative_team_reaction_can_force_leave(self) -> None:
        sid = "sess_team_reaction_leave"
        self._seed_context(sid)
        invite_npc_to_team(TeamInviteRequest(session_id=sid, npc_role_id="npc_local", player_prompt="一起行动吧。"))

        save = get_current_save(sid)
        save.team_state.members[0].affinity = 1
        save_current(save)

        response = apply_team_reactions(sid, trigger_kind="main_chat", player_text="我要威胁并抢劫路人。", summary="玩家做出了危险选择。")
        self.assertEqual(response.team_state.members, [])

        updated = get_current_save(sid)
        self.assertEqual(updated.team_state.members, [])
        self.assertEqual(updated.role_pool[0].state, "idle")

    def test_team_chat_records_member_responses_and_reactions(self) -> None:
        sid = "sess_team_chat"
        self._seed_context(sid)
        invite_npc_to_team(TeamInviteRequest(session_id=sid, npc_role_id="npc_local", player_prompt="一起行动吧。"))

        response = team_chat(TeamChatRequest(session_id=sid, player_message="谢谢你跟我一起行动。"))
        self.assertEqual(len(response.replies), 1)
        self.assertEqual(response.replies[0].member_role_id, "npc_local")
        self.assertIn(response.replies[0].response_mode, {"speech", "action"})

        updated = get_current_save(sid)
        self.assertTrue(any(item.trigger_kind == "team_chat" for item in updated.team_state.reactions))
        self.assertGreaterEqual(len(updated.role_pool[0].dialogue_logs), 2)

    def test_debug_teammate_background_preserves_long_ai_output(self) -> None:
        sid = "sess_debug_teammate_long_background"
        self._seed_context(sid)
        config = ChatConfig(
            openai_api_key="test-key",
            model="test-model",
            stream=False,
            gm_prompt="gm",
        )
        long_background = " ".join(f"segment{i}" for i in range(1, 30))
        ai_spec = {
            "display_name": "长风",
            "race": "人类",
            "char_class": "战士",
            "sheet_background": "城镇守望",
            "alignment": "neutral_good",
            "personality": "稳重",
            "speaking_style": "说话低声而克制",
            "appearance": "披着旧斗篷，手臂上有旧伤",
            "background": long_background,
            "cognition": "重视同伴承诺，也重视长期观察后的判断",
            "secret": "他仍在寻找一支失散多年的旧队伍，并把这件事压在心里。",
            "likes": ["旧地图"],
            "languages": ["通用语"],
            "tool_proficiencies": [],
            "skills_proficient": [],
            "features_traits": [],
            "spells": [],
            "preferred_weapon": "长剑",
            "preferred_armor": "锁子甲",
            "inventory_items": ["旧地图"],
            "notes": "long background test",
            "ability_bias": "strength",
        }

        with patch("app.services.team_service._ai_team_role_spec", return_value=ai_spec):
            created = generate_debug_teammate(
                TeamDebugGenerateRequest(session_id=sid, prompt="有长背景的战士", config=config)
            )

        self.assertIsNotNone(created.role)
        assert created.role is not None
        self.assertGreater(len(created.role.background), 120)
        self.assertIn("segment20", created.role.background)

    def test_debug_teammate_fallback_background_uses_prompt_topics(self) -> None:
        sid = "sess_debug_teammate_background_fallback"
        self._seed_context(sid)

        created = generate_debug_teammate(
            TeamDebugGenerateRequest(session_id=sid, prompt="精灵游侠，善用短弓，喜欢旧地图，寡言")
        )

        self.assertIsNotNone(created.role)
        assert created.role is not None
        self.assertGreater(len(created.role.background), 60)
        self.assertTrue(
            "旧地图" in created.role.background or "精灵" in created.role.background or "游侠" in created.role.background
        )
    def test_team_public_reaction_contains_visible_action(self) -> None:
        sid = "sess_team_public_reaction_action"
        self._seed_context(sid)
        invite_npc_to_team(TeamInviteRequest(session_id=sid, npc_role_id="npc_local", player_prompt="一起行动吧。"))
        save = get_current_save(sid)

        reactions = generate_team_public_replies_in_save(
            save,
            session_id=sid,
            player_text='{"input_type":"player_intent_v1","action_description":"我在大厅里抬手示意","speech_description":"大家先别紧张"}',
            scene_summary="玩家在大厅里公开发言",
            config=None,
        )

        self.assertEqual(len(reactions), 1)
        self.assertTrue(any(token in reactions[0].content for token in ["看", "点头", "侧过脸", "手", "目光", "收紧"]))


if __name__ == "__main__":
    unittest.main()
