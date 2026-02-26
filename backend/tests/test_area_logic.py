import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.storage import storage_state
from app.models.schemas import (
    AreaDiscoverInteractionsRequest,
    AreaExecuteInteractionRequest,
    AreaInteraction,
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    Coord3D,
    WorldClock,
    WorldClockInitRequest,
)
from app.services.world_service import (
    AIRegionGenerationError,
    _validate_discovered_interactions,
    clear_current_save,
    discover_interactions,
    execute_interaction,
    get_area_current,
    get_current_save,
    init_world_clock,
    move_to_sub_zone,
)
from app.models.schemas import AreaMoveSubZoneRequest


class AreaLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        storage_state.set_save_path(str(root / 'current-save.json'))
        storage_state.set_config_path(str(root / 'config.json'))

    def tearDown(self) -> None:
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        self._tmpdir.cleanup()

    def _seed_area(self, session_id: str) -> None:
        save = clear_current_save(session_id)
        save.area_snapshot = AreaSnapshot(
            zones=[
                AreaZone(
                    zone_id='zone_a',
                    name='A区',
                    center=Coord3D(x=0, y=0, z=0),
                    sub_zone_ids=['sub_a_1', 'sub_a_2'],
                )
            ],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id='sub_a_1',
                    zone_id='zone_a',
                    name='起点',
                    coord=Coord3D(x=0, y=0, z=0),
                    description='起点描述',
                    key_interactions=[
                        AreaInteraction(
                            interaction_id='int_base',
                            name='观察周边',
                            type='scene',
                            generated_mode='pre',
                            status='ready',
                            placeholder=True,
                        )
                    ],
                ),
                AreaSubZone(
                    sub_zone_id='sub_a_2',
                    zone_id='zone_a',
                    name='终点',
                    coord=Coord3D(x=600, y=0, z=0),
                    description='终点描述',
                ),
            ],
            current_zone_id='zone_a',
            current_sub_zone_id='sub_a_1',
            clock=WorldClock(calendar='fantasy_default', year=1024, month=3, day=14, hour=9, minute=30),
        )
        save.player_static_data.move_speed_mph = 4500
        from app.services.world_service import save_current

        save_current(save)

    def test_clock_init_and_move_duration(self) -> None:
        session_id = 'sess_test_move'
        init_resp = init_world_clock(WorldClockInitRequest(session_id=session_id, calendar='fantasy_default'))
        self.assertTrue(init_resp.ok)

        self._seed_area(session_id)
        moved = move_to_sub_zone(AreaMoveSubZoneRequest(session_id=session_id, to_sub_zone_id='sub_a_2'))
        self.assertTrue(moved.ok)
        self.assertEqual(moved.duration_min, 8)
        self.assertEqual(moved.clock_after.minute, 38)

    def test_placeholder_execute_advances_clock(self) -> None:
        session_id = 'sess_test_execute'
        self._seed_area(session_id)

        before = get_area_current(session_id).area_snapshot.clock
        self.assertIsNotNone(before)

        resp = execute_interaction(AreaExecuteInteractionRequest(session_id=session_id, interaction_id='int_base'))
        self.assertTrue(resp.ok)
        self.assertEqual(resp.message, '待开发')

        after = get_area_current(session_id).area_snapshot.clock
        self.assertIsNotNone(after)
        self.assertEqual((before.minute + 1) % 60, after.minute)

    def test_discover_dedup_strategy(self) -> None:
        session_id = 'sess_test_discover'
        self._seed_area(session_id)

        with patch('app.services.world_service._ai_discover_interactions', return_value=[
            {'name': '观察周边', 'type': 'scene', 'status': 'ready'},
            {'name': '查看门后刻痕', 'type': 'item', 'status': 'ready'},
            {'name': '查看门后刻痕', 'type': 'item', 'status': 'ready'},
        ]):
            resp = discover_interactions(
                AreaDiscoverInteractionsRequest(
                    session_id=session_id,
                    sub_zone_id='sub_a_1',
                    intent='观察墙壁',
                    config={
                        'version': '1.0.0',
                        'openai_api_key': 'sk-test',
                        'model': 'gpt-4.1-mini',
                        'stream': False,
                        'temperature': 0.8,
                        'max_tokens': 512,
                        'gm_prompt': 'test',
                    },
                )
            )

        self.assertEqual(resp.generated_mode, 'instant')
        self.assertEqual(len(resp.new_interactions), 1)
        self.assertEqual(resp.new_interactions[0].name, '查看门后刻痕')

    def test_discover_schema_validation(self) -> None:
        with self.assertRaises(AIRegionGenerationError):
            _validate_discovered_interactions({'bad_key': []})


if __name__ == '__main__':
    unittest.main()
