import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.storage import storage_state
from app.models.schemas import ChatConfig, InventoryItem, PlayerInputValidationRequest
from app.services.player_input_validation_service import PLAYER_INPUT_VALIDATION_FAILED, validate_player_input
from app.services.world_service import clear_current_save, save_current


class PlayerInputValidationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))
        self.session_id = "sess_player_input_validation"

    def tearDown(self) -> None:
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        self._tmpdir.cleanup()

    def _chat_config(self) -> ChatConfig:
        return ChatConfig(api_key="test-key", model="test-model", stream=False, gm_prompt="gm")

    def _seed_player(self) -> str:
        save = clear_current_save(self.session_id)
        player = save.player_static_data
        player.name = "Player"
        player.dnd5e_sheet.spells = ["Fireball"]
        player.dnd5e_sheet.war_arts = ["Power Strike"]
        player.dnd5e_sheet.spell_slots_max.level_1 = 1
        player.dnd5e_sheet.spell_slots_current.level_1 = 1
        player.dnd5e_sheet.martial_points_current = 1
        player.dnd5e_sheet.backpack.items = [
            InventoryItem(item_id="sword_1", name="Iron Sword", item_type="weapon", slot_type="weapon", quantity=1),
            InventoryItem(item_id="potion_1", name="Healing Potion", item_type="consumable", slot_type="misc", quantity=2),
        ]
        save_current(save)
        return player.player_id

    def test_speech_only_input_skips_validation(self) -> None:
        actor_role_id = self._seed_player()

        response = validate_player_input(
            PlayerInputValidationRequest(
                session_id=self.session_id,
                entry_point="main_chat",
                action_text="",
                speech_text="我先看看。",
                actor_role_id=actor_role_id,
            )
        )

        self.assertEqual(response.status, "accepted")
        self.assertEqual(response.normalized_action_text, "")
        self.assertEqual(response.normalized_speech_text, "我先看看。")
        self.assertEqual(response.issues, [])

    def test_multiple_world_actions_keeps_first_action(self) -> None:
        actor_role_id = self._seed_player()
        with patch(
            "app.services.player_input_validation_service._call_validation_model",
            return_value={
                "normalized_action_text": "我先踹门。",
                "normalized_speech_text": "",
                "fallback_action_text": "我先踹门。",
                "issue_codes": ["multiple_world_actions"],
                "resource_kind": "none",
                "resource_name": "",
                "suggested_action_type": "check",
            },
        ):
            response = validate_player_input(
                PlayerInputValidationRequest(
                    session_id=self.session_id,
                    entry_point="main_chat",
                    action_text="我踹门，再掀桌子。",
                    speech_text="",
                    actor_role_id=actor_role_id,
                    config=self._chat_config(),
                )
            )

        self.assertEqual(response.status, "needs_player_confirmation")
        self.assertEqual(response.normalized_action_text, "我先踹门。")
        self.assertEqual(response.fallback_action_text, "我先踹门。")
        self.assertEqual([issue.code for issue in response.issues], ["multiple_world_actions"])

    def test_spell_known_and_slots_available_passes(self) -> None:
        actor_role_id = self._seed_player()
        with patch(
            "app.services.player_input_validation_service._call_validation_model",
            return_value={
                "normalized_action_text": "我施放火球术。",
                "normalized_speech_text": "",
                "fallback_action_text": "我抬手准备施法。",
                "issue_codes": [],
                "resource_kind": "spell",
                "resource_name": "fireball",
                "suggested_action_type": "check",
            },
        ):
            response = validate_player_input(
                PlayerInputValidationRequest(
                    session_id=self.session_id,
                    entry_point="public_turn_action",
                    action_text="我施放火球术。",
                    speech_text="",
                    actor_role_id=actor_role_id,
                    config=self._chat_config(),
                )
            )

        self.assertEqual(response.status, "accepted")
        self.assertEqual(response.resource_status.check_status, "passed")
        self.assertEqual(response.resource_status.resource_kind, "spell")
        self.assertEqual(response.issues, [])

    def test_spell_slots_insufficient_fails(self) -> None:
        actor_role_id = self._seed_player()
        save = clear_current_save(self.session_id)
        save.player_static_data.name = "Player"
        save.player_static_data.dnd5e_sheet.spells = ["Fireball"]
        save.player_static_data.dnd5e_sheet.spell_slots_max.level_1 = 1
        save.player_static_data.dnd5e_sheet.spell_slots_current.level_1 = 0
        save_current(save)
        actor_role_id = save.player_static_data.player_id

        with patch(
            "app.services.player_input_validation_service._call_validation_model",
            return_value={
                "normalized_action_text": "我施放火球术。",
                "normalized_speech_text": "",
                "fallback_action_text": "我抬手摆出施法姿势。",
                "issue_codes": [],
                "resource_kind": "spell",
                "resource_name": "fireball",
                "suggested_action_type": "check",
            },
        ):
            response = validate_player_input(
                PlayerInputValidationRequest(
                    session_id=self.session_id,
                    entry_point="public_turn_action",
                    action_text="我施放火球术。",
                    speech_text="",
                    actor_role_id=actor_role_id,
                    config=self._chat_config(),
                )
            )

        self.assertEqual(response.status, "needs_player_confirmation")
        self.assertEqual(response.resource_status.check_status, "failed")
        self.assertIn("spell_slot_insufficient", [issue.code for issue in response.issues])
        self.assertEqual(response.fallback_action_text, "我抬手摆出施法姿势。")

    def test_spell_not_known_fails(self) -> None:
        actor_role_id = self._seed_player()
        save = clear_current_save(self.session_id)
        save.player_static_data.name = "Player"
        save.player_static_data.dnd5e_sheet.spells = []
        save_current(save)
        actor_role_id = save.player_static_data.player_id

        with patch(
            "app.services.player_input_validation_service._call_validation_model",
            return_value={
                "normalized_action_text": "我施放火球术。",
                "normalized_speech_text": "",
                "fallback_action_text": "我抬手准备攻击。",
                "issue_codes": [],
                "resource_kind": "spell",
                "resource_name": "fireball",
                "suggested_action_type": "check",
            },
        ):
            response = validate_player_input(
                PlayerInputValidationRequest(
                    session_id=self.session_id,
                    entry_point="main_chat",
                    action_text="我施放火球术。",
                    speech_text="",
                    actor_role_id=actor_role_id,
                    config=self._chat_config(),
                )
            )

        self.assertIn("spell_not_known", [issue.code for issue in response.issues])

    def test_war_art_requires_weapon_fails(self) -> None:
        actor_role_id = self._seed_player()
        save = clear_current_save(self.session_id)
        save.player_static_data.name = "Player"
        save.player_static_data.dnd5e_sheet.war_arts = ["Power Strike"]
        save.player_static_data.dnd5e_sheet.martial_points_current = 1
        save.player_static_data.dnd5e_sheet.backpack.items = []
        save.player_static_data.dnd5e_sheet.equipment_slots.weapon_item_id = None
        save_current(save)
        actor_role_id = save.player_static_data.player_id

        with patch(
            "app.services.player_input_validation_service._call_validation_model",
            return_value={
                "normalized_action_text": "我使出强力一击。",
                "normalized_speech_text": "",
                "fallback_action_text": "我压低重心准备近战。",
                "issue_codes": [],
                "resource_kind": "war_art",
                "resource_name": "power_strike",
                "suggested_action_type": "attack",
            },
        ):
            response = validate_player_input(
                PlayerInputValidationRequest(
                    session_id=self.session_id,
                    entry_point="public_turn_attack_response",
                    action_text="我使出强力一击。",
                    speech_text="",
                    actor_role_id=actor_role_id,
                    config=self._chat_config(),
                )
            )

        self.assertIn("war_art_requires_weapon", [issue.code for issue in response.issues])

    def test_item_not_owned_fails(self) -> None:
        actor_role_id = self._seed_player()
        with patch(
            "app.services.player_input_validation_service._call_validation_model",
            return_value={
                "normalized_action_text": "我喝治疗药水。",
                "normalized_speech_text": "",
                "fallback_action_text": "我摸向腰包确认物资。",
                "issue_codes": [],
                "resource_kind": "item",
                "resource_name": "unknown_potion",
                "suggested_action_type": "item_use",
            },
        ):
            response = validate_player_input(
                PlayerInputValidationRequest(
                    session_id=self.session_id,
                    entry_point="main_chat",
                    action_text="我喝治疗药水。",
                    speech_text="",
                    actor_role_id=actor_role_id,
                    config=self._chat_config(),
                )
            )

        self.assertIn("item_not_owned", [issue.code for issue in response.issues])

    def test_speech_only_required_when_unable_to_act(self) -> None:
        actor_role_id = self._seed_player()
        save = clear_current_save(self.session_id)
        save.player_static_data.name = "Player"
        save.player_static_data.dnd5e_sheet.hit_points.current = 0
        save.player_static_data.dnd5e_sheet.death_state.life_status = "dying"
        save_current(save)
        actor_role_id = save.player_static_data.player_id

        with patch(
            "app.services.player_input_validation_service._call_validation_model",
            return_value={
                "normalized_action_text": "我挣扎着站起来。",
                "normalized_speech_text": "救我。",
                "fallback_action_text": "我挣扎着挪动身体。",
                "issue_codes": [],
                "resource_kind": "none",
                "resource_name": "",
                "suggested_action_type": "check",
            },
        ):
            response = validate_player_input(
                PlayerInputValidationRequest(
                    session_id=self.session_id,
                    entry_point="public_turn_attack_response",
                    action_text="我挣扎着站起来。",
                    speech_text="救我。",
                    actor_role_id=actor_role_id,
                    config=self._chat_config(),
                )
            )

        self.assertIn("speech_only_required", [issue.code for issue in response.issues])
        self.assertEqual(response.fallback_action_text, "")
        self.assertIn("Speech: 救我。", response.display_text)

    def test_actor_dead_returns_actor_dead(self) -> None:
        actor_role_id = self._seed_player()
        save = clear_current_save(self.session_id)
        save.player_static_data.name = "Player"
        save.player_static_data.dnd5e_sheet.hit_points.current = 0
        save.player_static_data.dnd5e_sheet.death_state.life_status = "dead"
        save_current(save)
        actor_role_id = save.player_static_data.player_id

        with patch(
            "app.services.player_input_validation_service._call_validation_model",
            return_value={
                "normalized_action_text": "我继续攻击。",
                "normalized_speech_text": "",
                "fallback_action_text": "我握紧武器。",
                "issue_codes": [],
                "resource_kind": "none",
                "resource_name": "",
                "suggested_action_type": "attack",
            },
        ):
            response = validate_player_input(
                PlayerInputValidationRequest(
                    session_id=self.session_id,
                    entry_point="public_turn_action",
                    action_text="我继续攻击。",
                    speech_text="",
                    actor_role_id=actor_role_id,
                    config=self._chat_config(),
                )
            )

        self.assertIn("actor_dead", [issue.code for issue in response.issues])
        self.assertEqual(response.fallback_action_text, "")

    def test_bad_ai_json_raises_validation_failed(self) -> None:
        actor_role_id = self._seed_player()

        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))],
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_: fake_response,
                )
            )
        )

        with patch("app.services.player_input_validation_service.create_sync_client", return_value=fake_client):
            with self.assertRaisesRegex(ValueError, PLAYER_INPUT_VALIDATION_FAILED):
                validate_player_input(
                    PlayerInputValidationRequest(
                        session_id=self.session_id,
                        entry_point="debug_panel",
                        action_text="我试着攻击。",
                        speech_text="",
                        actor_role_id=actor_role_id,
                        config=self._chat_config(),
                    )
                )
