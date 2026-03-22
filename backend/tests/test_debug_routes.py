import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.storage import storage_state
from app.core.user_context import get_current_user, set_current_user
from app.main import app
from app.models.schemas import (
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    ChatConfig,
    Coord3D,
    EncounterEntry,
    NpcDialogueEntry,
    NpcRoleCard,
    PendingTurnState,
    PlayerStaticData,
    Position,
    PublicTurnRound,
    RoleRelation,
    SubZoneChatTurn,
    TeamMember,
    TeamReaction,
    TemplateLibraryFillRequest,
    TokenUsageResponse,
)
from app.services.pending_turn_service import save_pending_turn
from app.services.template_library_debug_service import fill_template_library
from app.services.world_service import get_current_save, save_current


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


class DebugRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        self._orig_user = get_current_user()
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))
        set_current_user(None)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        set_current_user(self._orig_user)
        self._tmpdir.cleanup()

    def test_token_usage_route_resets_store_when_read_fails(self) -> None:
        fallback = TokenUsageResponse(session_id="sess_usage_route")
        with (
            patch("app.api.routes.token_usage_store.get", side_effect=RuntimeError("boom")),
            patch("app.api.routes.token_usage_store.reset", return_value=fallback) as mocked_reset,
        ):
            response = self.client.get("/api/v1/token-usage", params={"session_id": "sess_usage_route"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "sess_usage_route")
        mocked_reset.assert_called_once_with("sess_usage_route")

    def test_template_library_fill_route_returns_named_500_for_unexpected_error(self) -> None:
        with patch("app.api.routes.fill_template_library", side_effect=RuntimeError("disk locked")):
            response = self.client.post(
                "/api/v1/debug/template-library/fill",
                json={
                    "session_id": "sess_template_route",
                    "config": {
                        "provider": "openai",
                        "api_key": "test-key",
                        "model": "gpt-4o-mini",
                        "stream": False,
                        "gm_prompt": "You are a GM.",
                    },
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "template library fill failed")

    def test_fill_template_library_rejects_non_object_payload(self) -> None:
        req = TemplateLibraryFillRequest(session_id="sess_template_service", config=self._config())
        with patch(
            "app.services.template_library_debug_service.create_sync_client",
            return_value=_FakeSyncClient('["not-an-object"]'),
        ):
            with self.assertRaisesRegex(ValueError, "template library AI payload must be a JSON object"):
                fill_template_library(req)

    def test_fill_template_library_rejects_non_object_rows(self) -> None:
        req = TemplateLibraryFillRequest(session_id="sess_template_rows", config=self._config())
        with patch(
            "app.services.template_library_debug_service.create_sync_client",
            return_value=_FakeSyncClient(
                '{"item_definitions":["bad-row"],"equipment_definitions":[],"spell_definitions":[],"interactable_templates":[]}'
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "template library field 'item_definitions' item 0 must be an object",
            ):
                fill_template_library(req)

    def test_fill_template_library_accepts_stringified_spell_rows(self) -> None:
        req = TemplateLibraryFillRequest(session_id="sess_template_spell_rows", config=self._config())
        with patch(
            "app.services.template_library_debug_service.create_sync_client",
            return_value=_FakeSyncClient(
                (
                    '{"item_definitions":[],"equipment_definitions":[],'
                    '"spell_definitions":["{\\"definition_id\\":\\"lightning_bolt\\",\\"name\\":\\"Lightning Bolt\\",\\"attack_mode\\":\\"aoe_attack\\"}"],'
                    '"interactable_templates":[]}'
                )
            ),
        ):
            response = fill_template_library(req)

        self.assertEqual(response.appended_spell_definition_ids, ["lightning_bolt"])

    def test_fill_spell_library_ignores_invalid_non_spell_rows(self) -> None:
        req = TemplateLibraryFillRequest(
            session_id="sess_spell_rows",
            fill_scope="spells",
            spell_fill_count=5,
            config=self._config(),
        )
        with patch(
            "app.services.template_library_debug_service.create_sync_client",
            return_value=_FakeSyncClient(
                (
                    '{"item_definitions":["bad-row"],'
                    '"spell_definitions":[{"definition_id":"spell_fireball","name":"Fireball","attack_mode":"aoe_attack"}]}'
                )
            ),
        ):
            response = fill_template_library(req)

        self.assertEqual(response.appended_spell_definition_ids, ["spell_fireball"])
        self.assertGreaterEqual(response.spell_definition_count, 1)
        self.assertEqual(response.appended_item_definition_ids, [])
        self.assertEqual(response.appended_equipment_definition_ids, [])
        self.assertEqual(response.appended_interactable_template_ids, [])

    def test_fill_spell_library_accepts_id_alias_and_appends_new_spells(self) -> None:
        req = TemplateLibraryFillRequest(
            session_id="sess_spell_alias_rows",
            fill_scope="spells",
            spell_fill_count=5,
            config=self._config(),
        )
        with patch(
            "app.services.template_library_debug_service.create_sync_client",
            return_value=_FakeSyncClient(
                (
                    '{"spell_definitions":['
                    '{"id":"fire_bolt","name":"Fire Bolt","damage_type":"fire"},'
                    '{"id":"fireball","name":"Fireball","damage_type":"fire"},'
                    '{"id":"cure_wounds","name":"Cure Wounds","damage_type":"healing"},'
                    '{"id":"mage_hand","name":"Mage Hand"},'
                    '{"id":"shield","name":"Shield"}'
                    ']}'
                )
            ),
        ):
            response = fill_template_library(req)

        self.assertEqual(response.appended_spell_definition_ids, ["cure_wounds", "mage_hand", "shield"])
        self.assertEqual(response.updated_spell_definition_ids, [])

    def test_fill_spell_library_accepts_stringified_spell_definition_rows(self) -> None:
        req = TemplateLibraryFillRequest(
            session_id="sess_spell_string_rows",
            fill_scope="spells",
            spell_fill_count=5,
            config=self._config(),
        )
        with patch(
            "app.services.template_library_debug_service.create_sync_client",
            return_value=_FakeSyncClient(
                (
                    '{"spell_definitions":['
                    '"{\\"definition_id\\":\\"thunder_step\\",\\"name\\":\\"Thunder Step\\",\\"attack_mode\\":\\"aoe_attack\\"}",'
                    '"{\\"spell_id\\":\\"counterspell\\",\\"name\\":\\"Counterspell\\"}"'
                    ']}'
                )
            ),
        ):
            response = fill_template_library(req)

        self.assertEqual(sorted(response.appended_spell_definition_ids), ["counterspell", "thunder_step"])

    def test_fill_spell_library_accepts_stringified_spell_definition_list_field(self) -> None:
        req = TemplateLibraryFillRequest(
            session_id="sess_spell_string_list",
            fill_scope="spells",
            spell_fill_count=5,
            config=self._config(),
        )
        with patch(
            "app.services.template_library_debug_service.create_sync_client",
            return_value=_FakeSyncClient(
                (
                    '{"spell_definitions":"['
                    '{\\"definition_id\\":\\"misty_step\\",\\"name\\":\\"Misty Step\\",\\"attack_mode\\":\\"targeted_attack\\"},'
                    '{\\"id\\":\\"guiding_bolt\\",\\"name\\":\\"Guiding Bolt\\",\\"attack_mode\\":\\"targeted_attack\\"}'
                    ']"}'
                )
            ),
        ):
            response = fill_template_library(req)

        self.assertEqual(sorted(response.appended_spell_definition_ids), ["guiding_bolt", "misty_step"])

    def test_debug_save_reset_route_clears_encounter_public_turn_and_team_memory(self) -> None:
        session_id = "sess_debug_reset_route"
        save = get_current_save(session_id)
        save.map_snapshot.player_position = Position(x=3, y=4, z=0, zone_id="zone_square")
        save.area_snapshot = AreaSnapshot(
            zones=[
                AreaZone(
                    zone_id="zone_square",
                    name="广场",
                    center=Coord3D(x=0, y=0, z=0),
                    description="测试区域",
                    sub_zone_ids=["sub_square_1"],
                )
            ],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_square_1",
                    zone_id="zone_square",
                    name="老榕树广场",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="测试子区块",
                )
            ],
            current_zone_id="zone_square",
            current_sub_zone_id="sub_square_1",
        )
        save.player_runtime_data.current_position = Position(x=3, y=4, z=0, zone_id="zone_square")
        save.team_state.members = [
            TeamMember(
                role_id="role_teammate",
                name="缪儿",
                affinity=77,
                trust=66,
                last_reaction_at="2026-03-21T09:00:00+00:00",
                last_reaction_preview="上次反应",
            )
        ]
        save.team_state.reactions = [
            TeamReaction(
                reaction_id="team_reaction_1",
                member_role_id="role_teammate",
                member_name="缪儿",
                trigger_kind="public_turn",
                content="我记得刚才那轮的事。",
                affinity_delta=1,
                trust_delta=1,
            )
        ]
        save.role_pool = [
            NpcRoleCard(
                role_id="role_teammate",
                name="缪儿",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
                profile=PlayerStaticData(role_type="npc"),
                relations=[RoleRelation(target_role_id="player_001", relation_tag="ally", note="保留关系")],
                cognition_changes=["记忆 A"],
                attitude_changes=["态度 B"],
                dialogue_logs=[
                    NpcDialogueEntry(
                        id="dlg_1",
                        speaker="npc",
                        speaker_role_id="role_teammate",
                        speaker_name="缪儿",
                        context_kind="team_chat",
                        content="我们刚讨论过现场。",
                        world_time_text="第 1 天 上午",
                    )
                ],
                last_private_chat_at="2026-03-21T08:00:00+00:00",
                last_public_turn_at="2026-03-21T08:30:00+00:00",
            )
        ]
        save.encounter_state.encounters = [
            EncounterEntry(
                encounter_id="enc_active",
                type="event",
                status="active",
                title="进行中的遭遇",
                description="现场正在混乱。",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
            ),
            EncounterEntry(
                encounter_id="enc_queued",
                type="event",
                status="queued",
                title="排队遭遇",
                description="下一场遭遇。",
                zone_id="zone_square",
                sub_zone_id="sub_square_1",
            ),
        ]
        save.encounter_state.active_encounter_id = "enc_active"
        save.encounter_state.pending_ids = ["enc_queued"]
        sub_zone = save.area_snapshot.sub_zones[0]
        sub_zone.chat_context.public_turn_state.current_round = PublicTurnRound(round_id="round_current", round_number=2)
        sub_zone.chat_context.public_turn_state.round_history = [PublicTurnRound(round_id="round_old", round_number=1)]
        sub_zone.chat_context.public_turn_state.awaiting_player_entry = False
        sub_zone.chat_context.public_turn_state.situation_dc = 17
        sub_zone.chat_context.recent_turns = [
            SubZoneChatTurn(turn_id="turn_public", public_round_id="round_current", public_round_number=2),
            SubZoneChatTurn(turn_id="turn_encounter", active_encounter_id="enc_active", active_encounter_title="进行中的遭遇"),
            SubZoneChatTurn(turn_id="turn_keep", player_action="保留的主聊天记录"),
        ]
        save_current(save)
        save_pending_turn(
            PendingTurnState(
                pending_turn_id="pending_debug_reset",
                session_id=session_id,
                flow_kind="public_turn",
                status="awaiting_player_attack_response",
                public_round_id="round_current",
            )
        )
        with patch("app.api.routes._require_user", return_value="tester"):
            response = self.client.post("/api/v1/debug/save-reset", json={"session_id": session_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cleared_active_encounter_ids"], ["enc_active"])
        self.assertEqual(payload["cleared_pending_encounter_ids"], ["enc_queued"])
        self.assertEqual(set(payload["cleared_public_round_ids"]), {"round_current", "round_old"})
        self.assertEqual(payload["cleared_recent_turn_count"], 2)
        self.assertEqual(payload["cleared_team_member_role_ids"], ["role_teammate"])
        self.assertTrue(payload["cleared_pending_turn"])
        self.assertIn("测试重置完成", payload["summary"])

        save_payload = payload["save"]
        self.assertEqual(save_payload["map_snapshot"]["player_position"]["zone_id"], "zone_square")
        self.assertEqual(save_payload["player_runtime_data"]["current_position"]["zone_id"], "zone_square")
        self.assertEqual(save_payload["team_state"]["members"][0]["affinity"], 77)
        self.assertEqual(save_payload["team_state"]["members"][0]["trust"], 66)
        self.assertIsNone(save_payload["team_state"]["members"][0]["last_reaction_at"])
        self.assertEqual(save_payload["team_state"]["members"][0]["last_reaction_preview"], "")
        self.assertEqual(save_payload["team_state"]["reactions"], [])
        self.assertIsNone(save_payload["area_snapshot"]["sub_zones"][0]["chat_context"]["public_turn_state"]["current_round"])
        self.assertEqual(save_payload["area_snapshot"]["sub_zones"][0]["chat_context"]["public_turn_state"]["round_history"], [])
        self.assertEqual(
            [turn["turn_id"] for turn in save_payload["area_snapshot"]["sub_zones"][0]["chat_context"]["recent_turns"]],
            ["turn_keep"],
        )
        self.assertIsNone(save_payload["encounter_state"]["active_encounter_id"])
        self.assertEqual(save_payload["encounter_state"]["pending_ids"], [])
        self.assertEqual(save_payload["encounter_state"]["encounters"][0]["status"], "invalidated")
        self.assertEqual(save_payload["encounter_state"]["encounters"][0]["invalidated_reason"], "debug_test_reset")
        self.assertEqual(save_payload["encounter_state"]["encounters"][1]["status"], "invalidated")
        self.assertEqual(save_payload["role_pool"][0]["relations"][0]["relation_tag"], "ally")
        self.assertEqual(save_payload["role_pool"][0]["dialogue_logs"], [])
        self.assertEqual(save_payload["role_pool"][0]["cognition_changes"], [])
        self.assertEqual(save_payload["role_pool"][0]["attitude_changes"], [])
        self.assertIsNone(save_payload["role_pool"][0]["last_private_chat_at"])
        self.assertIsNone(save_payload["role_pool"][0]["last_public_turn_at"])
        self.assertEqual(save_payload["game_logs"][-1]["kind"], "debug_reset")
        self.assertFalse((storage_state.save_path.parent / "pending-turn-state.json").exists())

    @staticmethod
    def _config() -> ChatConfig:
        return ChatConfig(
            provider="openai",
            api_key="test-key",
            model="gpt-4o-mini",
            stream=False,
            gm_prompt="You are a GM.",
        )


if __name__ == "__main__":
    unittest.main()
