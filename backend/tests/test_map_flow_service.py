import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.storage import storage_state
from app.core.user_context import get_current_user, set_current_user
from app.models.schemas import (
    ActionCheckRequest,
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    ChatConfig,
    Coord3D,
    MoveRequest,
    Position,
    RegionGenerateRequest,
    WorldClock,
    Zone,
    ZoneSubZoneSeed,
)
from app.services.map_flow_service import bootstrap_world_map, generate_map_reply_once, move_world_map, run_action_check_with_state_sync
from app.services.world_service import clear_current_save, save_current


class MapFlowServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        self._orig_user = get_current_user()
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))
        set_current_user(None)

    def tearDown(self) -> None:
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        set_current_user(self._orig_user)
        self._tmpdir.cleanup()

    def _seed_world(self, session_id: str) -> None:
        save = clear_current_save(session_id)
        save.session_id = session_id
        save.player_static_data.move_speed_mph = 6000
        save.map_snapshot.player_position = Position(x=0, y=0, z=0, zone_id="zone_a")
        save.player_runtime_data.session_id = session_id
        save.player_runtime_data.current_position = save.map_snapshot.player_position
        save.map_snapshot.zones = [
            Zone(
                zone_id="zone_a",
                name="A区",
                x=0,
                y=0,
                z=0,
                radius_m=200,
                description="起点",
                tags=["town"],
                sub_zones=[ZoneSubZoneSeed(name="起点广场", description="起点子区")],
            ),
            Zone(
                zone_id="zone_b",
                name="B区",
                x=1200,
                y=0,
                z=0,
                radius_m=200,
                description="终点",
                tags=["forest"],
                sub_zones=[ZoneSubZoneSeed(name="终点林地", description="终点子区")],
            ),
        ]
        save.area_snapshot = AreaSnapshot(
            zones=[
                AreaZone(
                    zone_id="zone_a",
                    name="A区",
                    zone_type="town",
                    center=Coord3D(x=0, y=0, z=0),
                    sub_zone_ids=["sub_zone_a_1"],
                ),
                AreaZone(
                    zone_id="zone_b",
                    name="B区",
                    zone_type="forest",
                    center=Coord3D(x=1200, y=0, z=0),
                    sub_zone_ids=["sub_zone_b_1"],
                ),
            ],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_zone_a_1",
                    zone_id="zone_a",
                    name="起点广场",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="起点子区",
                ),
                AreaSubZone(
                    sub_zone_id="sub_zone_b_1",
                    zone_id="zone_b",
                    name="终点林地",
                    coord=Coord3D(x=1200, y=0, z=0),
                    description="终点子区",
                ),
            ],
            current_zone_id="zone_a",
            current_sub_zone_id="sub_zone_a_1",
            clock=WorldClock(calendar="fantasy_default", year=1024, month=3, day=14, hour=9, minute=30),
        )
        save_current(save)

    def test_bootstrap_world_map_returns_state_sync_for_existing_map(self) -> None:
        session_id = "sess_map_bootstrap"
        self._seed_world(session_id)

        response = asyncio.run(
            bootstrap_world_map(
                RegionGenerateRequest(
                    session_id=session_id,
                    config={
                        "version": "1.0.0",
                        "openai_api_key": "sk-test",
                        "model": "gpt-4.1-mini",
                        "stream": False,
                        "temperature": 0.8,
                        "max_tokens": 512,
                        "gm_prompt": "test",
                    },
                    player_position=Position(x=0, y=0, z=0, zone_id="zone_a"),
                    desired_count=6,
                    max_count=10,
                    world_prompt="",
                    force_regenerate=False,
                )
            )
        )

        self.assertFalse(response.generated)
        self.assertEqual(len(response.state_sync.map_snapshot.zones), 2)
        self.assertEqual(len(response.state_sync.render.nodes), 2)
        self.assertEqual(response.state_sync.area_snapshot.current_zone_id, "zone_a")
        self.assertIsNotNone(response.state_sync.current_zone_metric)
        self.assertGreaterEqual(len(response.state_sync.zone_metric_state.entries), 2)
        log_path = Path(storage_state.save_path.parent) / "debug" / "latest-generation-log.json"
        payload_json = json.loads(log_path.read_text(encoding="utf-8"))
        self.assertEqual(payload_json["flow_kind"], "map_bootstrap")
        self.assertEqual(payload_json["status"], "success")
        self.assertEqual(payload_json["result"]["state_sync"]["zone_count"], 2)

    def test_move_world_map_returns_narration_and_state_sync(self) -> None:
        session_id = "sess_map_move"
        self._seed_world(session_id)

        response = asyncio.run(
            move_world_map(
                MoveRequest(
                    session_id=session_id,
                    from_zone_id="zone_a",
                    to_zone_id="zone_b",
                    player_name="玩家",
                )
            )
        )

        self.assertEqual(response.new_position.zone_id, "zone_b")
        self.assertEqual(response.state_sync.area_snapshot.current_zone_id, "zone_b")
        self.assertTrue(response.narration.text)
        self.assertEqual(response.post_checks.trigger_kind, "random_move")
        self.assertEqual(response.state_sync.render.player_marker["x"], 1200)
        self.assertEqual(response.narration.source, "deterministic")
        self.assertIsNotNone(response.current_zone_metric)
        self.assertTrue(all(circle.fill_color for circle in response.state_sync.render.circles))

    def test_action_check_with_state_sync_returns_bundle(self) -> None:
        session_id = "sess_action_sync"
        self._seed_world(session_id)

        response = asyncio.run(
            run_action_check_with_state_sync(
                ActionCheckRequest(
                    session_id=session_id,
                    action_type="check",
                    action_prompt="我检查地面的痕迹",
                    forced_dice_roll=15,
                    return_state_sync=True,
                    post_trigger_kind="quest_rule",
                )
            )
        )

        self.assertIsNotNone(response.state_sync)
        self.assertIsNotNone(response.post_checks)
        self.assertEqual(response.post_checks.trigger_kind, "quest_rule")
        self.assertEqual(response.state_sync.area_snapshot.current_zone_id, "zone_a")

    def test_sub_zone_reply_falls_back_when_model_leaks_template_tokens(self) -> None:
        config = ChatConfig(api_key="sk-test", model="gpt-4.1-mini", stream=False, gm_prompt="test")
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="你离开了$from_id，走向$to_name。"))]
                    )
                )
            )
        )
        with patch("app.services.map_flow_service.create_sync_client", return_value=fake_client):
            response = generate_map_reply_once(
                session_id="sess_reply_fallback",
                config=config,
                kind="sub_zone_move",
                fallback_text="你移动到了新地点。",
                from_name="起点广场",
                to_name="终点林地",
                from_id="sub_zone_a_1",
                to_id="sub_zone_b_1",
                distance_m=12.5,
                duration_min=2,
            )
        self.assertEqual(response.text, "你移动到了新地点。")
        self.assertEqual(response.source, "deterministic")


if __name__ == "__main__":
    unittest.main()
