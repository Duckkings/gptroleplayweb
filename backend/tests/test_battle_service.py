import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.storage import storage_state
from app.main import app
from app.models.schemas import (
    AreaSubZone,
    AreaZone,
    Coord3D,
    Dnd5eCharacterSheet,
    Dnd5eHitPoints,
    NpcRoleCard,
    PlayerStaticData,
    TeamMember,
)
from app.services.world_service import get_current_save, save_current


class BattleServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))
        self.client = TestClient(app)
        save = get_current_save("sess_battle")
        save.session_id = "sess_battle"
        save.area_snapshot.current_zone_id = "zone_test"
        save.area_snapshot.current_sub_zone_id = "sub_zone_test"
        save.area_snapshot.zones = [
            AreaZone(
                zone_id="zone_test",
                name="测试大区块",
                zone_type="city",
                center=Coord3D(x=0, y=0, z=0),
                description="测试用区域",
                sub_zone_ids=["sub_zone_test"],
            )
        ]
        save.area_snapshot.sub_zones = [
            AreaSubZone(
                sub_zone_id="sub_zone_test",
                zone_id="zone_test",
                name="测试子区块",
                coord=Coord3D(x=0, y=0, z=0),
                description="石板路和空旷巷口。",
            )
        ]
        save.player_static_data = PlayerStaticData(
            player_id="player_001",
            name="玩家",
            dnd5e_sheet=Dnd5eCharacterSheet(
                level=2,
                armor_class=13,
                initiative_bonus=2,
                hit_points=Dnd5eHitPoints(current=18, maximum=18, temporary=0),
            ),
        )
        ally = NpcRoleCard(role_id="npc_team_1", name="缨儿")
        ally.profile.dnd5e_sheet.armor_class = 12
        ally.profile.dnd5e_sheet.hit_points.current = 14
        ally.profile.dnd5e_sheet.hit_points.maximum = 14
        ally.profile.dnd5e_sheet.initiative_bonus = 1
        save.role_pool = [ally]
        save.team_state.members = [TeamMember(role_id="npc_team_1", name="缨儿", status="active")]
        save_current(save)

    def tearDown(self) -> None:
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        self._tmpdir.cleanup()

    def test_start_debug_battle_creates_sandbox_with_player_initiative_prompt(self) -> None:
        with patch("app.services.battle_service.random_d20", side_effect=[8, 7, 6, 5]):
            response = self.client.post(
                "/api/v1/battle/debug/start",
                json={
                    "session_id": "sess_battle",
                    "mode": "template",
                    "template_group": "流氓小队",
                    "ai_scale": "single",
                    "ai_strength": "standard",
                    "ai_pacing": "step",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["battle"]["status"], "awaiting_player_roll")
        self.assertEqual(data["battle"]["pending_roll"]["roll_kind"], "initiative")
        self.assertEqual(data["battle"]["battlefield"]["sub_zone_name"], "测试子区块")

        current = self.client.get("/api/v1/battle/debug/current", params={"session_id": "sess_battle"})
        self.assertEqual(current.status_code, 200)
        self.assertIsNotNone(current.json()["battle"])

    def test_resolve_initiative_and_end_battle_preserves_formal_state(self) -> None:
        with patch("app.services.battle_service.random_d20", side_effect=[5, 4, 3, 2]):
            start = self.client.post(
                "/api/v1/battle/debug/start",
                json={
                    "session_id": "sess_battle",
                    "mode": "template",
                    "template_group": "持刀混混",
                    "ai_scale": "single",
                    "ai_strength": "standard",
                    "ai_pacing": "step",
                },
            )

        self.assertEqual(start.status_code, 200)
        battle_id = start.json()["battle"]["battle_id"]
        resolved = self.client.post(
            f"/api/v1/battle/{battle_id}/resolve-roll",
            json={"session_id": "sess_battle", "forced_dice_roll": 18},
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertIn(resolved.json()["battle"]["status"], {"awaiting_player_action", "awaiting_ai_continue"})

        ended = self.client.post(
            f"/api/v1/battle/{battle_id}/end",
            json={"session_id": "sess_battle"},
        )
        self.assertEqual(ended.status_code, 200)

        save = get_current_save("sess_battle")
        self.assertEqual(save.player_static_data.dnd5e_sheet.hit_points.current, 18)
        self.assertEqual(save.role_pool[0].profile.dnd5e_sheet.hit_points.current, 14)
        self.assertTrue(any(log.kind == "battle_sandbox" for log in save.game_logs))


if __name__ == "__main__":
    unittest.main()
