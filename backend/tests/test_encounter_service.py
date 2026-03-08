import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.storage import storage_state
from app.models.schemas import (
    ActionCheckResponse,
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    ChatConfig,
    Coord3D,
    EncounterActRequest,
    EncounterCheckRequest,
    EncounterEntry,
    EncounterEscapeRequest,
    EncounterRejoinRequest,
    EncounterTerminationCondition,
)
from app.services.encounter_service import (
    act_on_encounter,
    advance_active_encounter_in_save,
    check_for_encounter,
    escape_encounter,
    get_encounter_debug_overview,
    rejoin_encounter,
)
from app.services.world_service import clear_current_save, get_current_save, save_current


class EncounterServiceTests(unittest.TestCase):
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
            zones=[AreaZone(zone_id="zone_town", name="Town", center=Coord3D(x=0, y=0, z=0), sub_zone_ids=["sub_town_1"])],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_town_1",
                    zone_id="zone_town",
                    name="Square",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="Square",
                )
            ],
            current_zone_id="zone_town",
            current_sub_zone_id="sub_town_1",
            clock=save.area_snapshot.clock,
        )
        save_current(save)

    def test_encounter_generation_includes_termination_conditions(self) -> None:
        sid = "sess_encounter_generate"
        self._seed_context(sid)
        save = get_current_save(sid)
        save.encounter_state.debug_force_trigger = True
        save_current(save)

        response = check_for_encounter(EncounterCheckRequest(session_id=sid, trigger_kind="debug_forced"))

        self.assertTrue(response.generated)
        self.assertIsNotNone(response.encounter)
        assert response.encounter is not None
        self.assertGreaterEqual(len(response.encounter.termination_conditions), 1)

    def test_escape_success_keeps_encounter_visible_and_background_tick_advances(self) -> None:
        sid = "sess_encounter_escape"
        self._seed_context(sid)
        save = get_current_save(sid)
        encounter = EncounterEntry(
            encounter_id="enc_test",
            type="npc",
            status="active",
            title="Bandit Clash",
            description="Bandits close in.",
            zone_id="zone_town",
            sub_zone_id="sub_town_1",
            player_presence="engaged",
            termination_conditions=[
                EncounterTerminationCondition(condition_id="cond_escape", kind="player_escapes", description="Player escapes"),
                EncounterTerminationCondition(condition_id="cond_goal", kind="target_resolved", description="Conflict resolved"),
            ],
        )
        save.encounter_state.encounters = [encounter]
        save.encounter_state.active_encounter_id = encounter.encounter_id
        save_current(save)

        action_result = ActionCheckResponse(
            session_id=sid,
            actor_role_id="player_001",
            action_type="check",
            requires_check=True,
            ability_used="dexterity",
            ability_modifier=2,
            dc=10,
            dice_roll=18,
            total_score=20,
            success=True,
            critical="none",
            time_spent_min=3,
            narrative="You get away.",
            applied_effects=[],
            relation_tag_suggestion=None,
        )

        with patch("app.services.world_service.action_check", return_value=action_result):
            result = escape_encounter(encounter.encounter_id, EncounterEscapeRequest(session_id=sid))

        self.assertTrue(result.escape_success)
        self.assertEqual(result.status, "escaped")
        self.assertEqual(result.encounter.player_presence, "away")
        self.assertEqual(result.encounter_state.active_encounter_id, encounter.encounter_id)

        updated = get_current_save(sid)
        advanced = advance_active_encounter_in_save(updated, session_id=sid, minutes_elapsed=5)
        self.assertIsNotNone(advanced)
        assert advanced is not None
        self.assertEqual(advanced.background_tick_count, 1)

    def test_rejoin_requires_return_to_origin_sub_zone(self) -> None:
        sid = "sess_encounter_rejoin"
        self._seed_context(sid)
        save = get_current_save(sid)
        encounter = EncounterEntry(
            encounter_id="enc_rejoin",
            type="event",
            status="escaped",
            title="Runaway Cart",
            description="A cart is out of control.",
            zone_id="zone_town",
            sub_zone_id="sub_town_1",
            player_presence="away",
            termination_conditions=[EncounterTerminationCondition(condition_id="cond_goal", kind="target_resolved", description="Cart stopped")],
        )
        save.encounter_state.encounters = [encounter]
        save.encounter_state.active_encounter_id = encounter.encounter_id
        save.area_snapshot.current_sub_zone_id = "sub_other"
        save_current(save)

        with self.assertRaises(ValueError):
            rejoin_encounter(encounter.encounter_id, EncounterRejoinRequest(session_id=sid))

    def test_old_presented_status_is_compatible_on_load(self) -> None:
        raw = {
            "encounter_id": "enc_old",
            "type": "event",
            "status": "presented",
            "title": "Legacy",
            "description": "Legacy encounter",
        }
        encounter = EncounterEntry.model_validate(raw)
        self.assertEqual(encounter.status, "active")

    def test_debug_overview_returns_active_or_queued_summary(self) -> None:
        sid = "sess_encounter_debug"
        self._seed_context(sid)
        save = get_current_save(sid)
        save.encounter_state.encounters = [
            EncounterEntry(
                encounter_id="enc_dbg",
                type="event",
                status="active",
                title="Debug Encounter",
                description="Debug description",
                zone_id="zone_town",
                sub_zone_id="sub_town_1",
                player_presence="engaged",
            )
        ]
        save.encounter_state.active_encounter_id = "enc_dbg"
        save_current(save)

        overview = get_encounter_debug_overview(sid)
        self.assertIsNotNone(overview.active_encounter)
        self.assertIn("当前活跃遭遇", overview.summary)
    def test_ai_generated_encounter_english_output_falls_back_to_chinese(self) -> None:
        sid = "sess_encounter_force_chinese_generate"
        self._seed_context(sid)
        save = get_current_save(sid)
        save.encounter_state.debug_force_trigger = True
        save_current(save)
        config = ChatConfig(openai_api_key="test-key", model="test-model", stream=False, gm_prompt="gm")

        class _FakeResponse:
            def __init__(self) -> None:
                self.choices = [type("Choice", (), {"message": type("Message", (), {"content": '{"type":"event","title":"Strange Noise","description":"A suspicious sound echoes near the square.","scene_summary":"The square grows tense.","termination_conditions":[{"kind":"time_elapsed","description":"Time passes."}],"tags":["odd"]}'})()})]

        fake_client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": type("Completions", (), {"create": lambda *args, **kwargs: _FakeResponse()})()})()},
        )()

        with patch("app.services.encounter_service.OpenAI", return_value=fake_client):
            response = check_for_encounter(EncounterCheckRequest(session_id=sid, trigger_kind="debug_forced", config=config))

        self.assertTrue(response.generated)
        self.assertIsNotNone(response.encounter)
        assert response.encounter is not None
        self.assertRegex(response.encounter.title, r"[\u4e00-\u9fff]")
        self.assertRegex(response.encounter.description, r"[\u4e00-\u9fff]")
        self.assertRegex(response.encounter.scene_summary, r"[\u4e00-\u9fff]")
        self.assertRegex(response.encounter.termination_conditions[0].description, r"[\u4e00-\u9fff]")

    def test_ai_step_english_output_falls_back_to_chinese(self) -> None:
        sid = "sess_encounter_force_chinese_step"
        self._seed_context(sid)
        save = get_current_save(sid)
        encounter = EncounterEntry(
            encounter_id="enc_step",
            type="event",
            status="active",
            title="夜巷异响",
            description="你听见巷口传来不自然的摩擦声。",
            zone_id="zone_town",
            sub_zone_id="sub_town_1",
            player_presence="engaged",
            scene_summary="巷口的异响正在逼近。",
            termination_conditions=[EncounterTerminationCondition(condition_id="cond_goal", kind="target_resolved", description="异响来源被查明。")],
        )
        save.encounter_state.encounters = [encounter]
        save.encounter_state.active_encounter_id = encounter.encounter_id
        save_current(save)
        config = ChatConfig(openai_api_key="test-key", model="test-model", stream=False, gm_prompt="gm")

        class _FakeResponse:
            def __init__(self) -> None:
                self.choices = [type("Choice", (), {"message": type("Message", (), {"content": '{"reply":"You move closer and inspect the alley.","time_spent_min":2,"scene_summary":"The alley grows tense.","step_kind":"gm_update","termination_updates":[]}'})()})]

        fake_client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": type("Completions", (), {"create": lambda *args, **kwargs: _FakeResponse()})()})()},
        )()

        with patch("app.services.encounter_service.OpenAI", return_value=fake_client):
            result = act_on_encounter(
                encounter.encounter_id,
                EncounterActRequest(session_id=sid, player_prompt="我压低脚步，靠近巷口观察。", config=config),
            )

        self.assertRegex(result.reply, r"[\u4e00-\u9fff]")
        self.assertRegex(result.encounter.scene_summary, r"[\u4e00-\u9fff]")


if __name__ == "__main__":
    unittest.main()
