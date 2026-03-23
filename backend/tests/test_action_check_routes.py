import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.storage import storage_state
from app.main import app
from app.models.schemas import ActionCheckPlanResponse, ActionCheckResponse


class ActionCheckRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        self._tmpdir.cleanup()

    def test_action_check_plan_route_returns_planned_payload(self) -> None:
        planned = ActionCheckPlanResponse(
            session_id="sess_action_plan_route",
            actor_role_id="player_001",
            actor_name="Player",
            actor_kind="player",
            action_type="check",
            requires_check=True,
            ability_used="wisdom",
            ability_modifier=2,
            dc=13,
            time_spent_min=2,
            check_task="判断能否识破埋伏",
        )

        with patch("app.api.routes.plan_action_check", return_value=planned):
            response = self.client.post(
                "/api/v1/actions/check/plan",
                json={
                    "session_id": "sess_action_plan_route",
                    "action_type": "check",
                    "action_prompt": "我仔细观察四周",
                    "actor_role_id": "player_001",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["check_task"], "判断能否识破埋伏")
        self.assertEqual(data["dc"], 13)
        self.assertEqual(data["actor_kind"], "player")

    def test_action_check_route_returns_409_when_player_roll_is_required(self) -> None:
        with patch("app.api.routes.action_check", side_effect=ValueError("PLAYER_DICE_ROLL_REQUIRED")):
            response = self.client.post(
                "/api/v1/actions/check",
                json={
                    "session_id": "sess_action_check_route",
                    "action_type": "check",
                    "action_prompt": "我强行撬门",
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "PLAYER_DICE_ROLL_REQUIRED")

    def test_action_check_route_returns_response_body(self) -> None:
        result = ActionCheckResponse(
            session_id="sess_action_check_ok",
            actor_role_id="player_001",
            actor_name="Player",
            actor_kind="player",
            action_type="check",
            requires_check=True,
            ability_used="dexterity",
            ability_modifier=3,
            dc=14,
            check_task="翻过木栅栏",
            dice_roll=12,
            total_score=15,
            success=True,
            critical="none",
            time_spent_min=2,
            narrative="【检定】Player 进行“翻过木栅栏”检定。",
            applied_effects=[],
            relation_tag_suggestion=None,
            scene_events=[],
        )

        with patch("app.api.routes.action_check", return_value=result):
            response = self.client.post(
                "/api/v1/actions/check",
                json={
                    "session_id": "sess_action_check_ok",
                    "action_type": "check",
                    "action_prompt": "我翻过木栅栏",
                    "forced_dice_roll": 12,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["actor_name"], "Player")
        self.assertEqual(data["check_task"], "翻过木栅栏")
        self.assertEqual(data["dice_roll"], 12)


    def test_action_check_route_uses_state_sync_runner(self) -> None:
        result = {
            "ok": True,
            "session_id": "sess_action_check_sync",
            "actor_role_id": "player_001",
            "actor_name": "Player",
            "actor_kind": "player",
            "action_type": "check",
            "requires_check": False,
            "ability_used": "wisdom",
            "ability_modifier": 2,
            "dc": 10,
            "check_task": "观察周围",
            "dice_roll": None,
            "total_score": None,
            "success": True,
            "critical": "none",
            "time_spent_min": 1,
            "narrative": "观察成功。",
            "applied_effects": [],
            "relation_tag_suggestion": None,
            "scene_events": [],
            "state_sync": {
                "map_snapshot": {"player_position": None, "zones": []},
                "area_snapshot": {"version": "0.1.0", "zones": [], "sub_zones": [], "current_zone_id": None, "current_sub_zone_id": None, "clock": None},
                "render": {"viewport": {"min_x": 0, "max_x": 0, "min_y": 0, "max_y": 0}, "nodes": [], "sub_nodes": [], "circles": [], "player_marker": {"x": 0, "y": 0}},
                "world_state": {"version": "0.1.0", "world_revision": 1, "map_revision": 1, "last_consistency_check_at": None, "last_world_rebuild_at": None},
                "player_static_data": {"player_id": "player_001", "name": "Player", "move_speed_mph": 3, "role_type": "player", "dnd5e_sheet": {"level": 1, "proficiency_bonus": 2, "ability_scores": {"strength": 10, "dexterity": 10, "constitution": 10, "intelligence": 10, "wisdom": 10, "charisma": 10}, "ability_modifiers": {"strength": 0, "dexterity": 0, "constitution": 0, "intelligence": 0, "wisdom": 0, "charisma": 0}, "hit_points": {"current": 10, "maximum": 10}, "armor_class": 10, "speed_ft": 30, "spell_slots": {"level_1": 0, "level_2": 0, "level_3": 0, "level_4": 0, "level_5": 0, "level_6": 0, "level_7": 0, "level_8": 0, "level_9": 0}, "stamina": {"current": 10, "maximum": 10}, "weapon": None, "armor": None, "backpack": {"items": []}, "buffs": [], "spells": [], "skills": []}},
                "player_runtime_data": {"session_id": "sess_action_check_sync", "current_position": None, "updated_at": "2026-03-14T00:00:00+00:00"},
                "role_pool": [],
                "current_reputation": None,
                "quest_state": {"version": "0.1.0", "tracked_quest_id": None, "quests": [], "updated_at": "2026-03-14T00:00:00+00:00"},
                "pending_offers": [],
                "tracked_quest": None,
                "encounter_state": {"version": "0.1.0", "encounters": [], "pending_ids": [], "active_encounter_id": None, "history": [], "debug_force_trigger": False, "updated_at": "2026-03-14T00:00:00+00:00"},
                "pending_encounters": [],
                "active_encounter": None,
                "fate_state": {"version": "0.1.0", "current_fate": None, "archive": [], "updated_at": "2026-03-14T00:00:00+00:00"},
                "team_state": {"version": "0.1.0", "members": [], "reactions": [], "updated_at": "2026-03-14T00:00:00+00:00"},
                "team_members": [],
                "game_logs": [],
            },
            "post_checks": {"trigger_kind": "quest_rule", "quests_evaluated": True, "fate_evaluated": True, "encounter_checked": True, "encounter_generated": False, "generated_encounter_id": None, "blocked_by_higher_priority_modal": False},
        }

        with patch("app.api.routes.run_action_check_with_state_sync", new=AsyncMock(return_value=result)) as mocked:
            response = self.client.post(
                "/api/v1/actions/check",
                json={
                    "session_id": "sess_action_check_sync",
                    "action_type": "check",
                    "action_prompt": "观察周围",
                    "return_state_sync": True,
                    "post_trigger_kind": "quest_rule",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["post_checks"]["trigger_kind"], "quest_rule")
        mocked.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
