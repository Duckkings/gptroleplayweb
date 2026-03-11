import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.storage import storage_state
from app.models.schemas import (
    ChatConfig,
    AreaDiscoverInteractionsRequest,
    AreaExecuteInteractionRequest,
    AreaInteraction,
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    Coord3D,
    NpcRoleCard,
    PlayerStaticData,
    Position,
    RegionGenerateRequest,
    MoveRequest,
    WorldClock,
    WorldClockInitRequest,
    Zone,
    ZoneSubZoneSeed,
)
from app.services.world_service import (
    AIRegionGenerationError,
    _ai_generate_zones,
    _validate_discovered_interactions,
    clear_current_save,
    discover_interactions,
    execute_interaction,
    get_area_current,
    get_current_save,
    generate_regions,
    init_world_clock,
    move_to_zone,
    move_to_sub_zone,
    save_current,
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

    def test_force_regenerate_clears_stale_role_pool_and_area_data(self) -> None:
        session_id = 'sess_force_regen'
        save = clear_current_save(session_id)
        save.session_id = session_id
        save.map_snapshot.zones = [
            Zone(
                zone_id='zone_old',
                name='旧区块',
                x=0,
                y=0,
                z=0,
                description='old',
                tags=['old'],
                sub_zones=[ZoneSubZoneSeed(name='旧子区', description='old')],
            )
        ]
        save.area_snapshot = AreaSnapshot(
            zones=[
                AreaZone(
                    zone_id='zone_old',
                    name='旧区块',
                    center=Coord3D(x=0, y=0, z=0),
                    sub_zone_ids=['sub_zone_old_1'],
                )
            ],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id='sub_zone_old_1',
                    zone_id='zone_old',
                    name='旧子区',
                    coord=Coord3D(x=0, y=0, z=0),
                    description='old',
                )
            ],
            current_zone_id='zone_old',
            current_sub_zone_id='sub_zone_old_1',
            clock=WorldClock(calendar='fantasy_default', year=1024, month=3, day=14, hour=9, minute=30),
        )
        save.role_pool = [
            NpcRoleCard(
                role_id='npc_old',
                name='旧NPC',
                zone_id='zone_old',
                sub_zone_id='sub_zone_old_1',
                profile=PlayerStaticData(role_type='npc'),
            )
        ]
        from app.services.world_service import save_current

        save_current(save)

        new_zone = Zone(
            zone_id='zone_new',
            name='新区块',
            x=100,
            y=100,
            z=0,
            description='new',
            tags=['new'],
            sub_zones=[ZoneSubZoneSeed(name='新子区', description='new')],
        )
        with patch('app.services.world_service._ai_generate_zones', return_value=[new_zone]):
            resp = generate_regions(
                RegionGenerateRequest(
                    session_id=session_id,
                    config=ChatConfig(
                        version='1.0.0',
                        openai_api_key='sk-test',
                        model='gpt-4.1-mini',
                        stream=False,
                        temperature=0.8,
                        max_tokens=256,
                        gm_prompt='test',
                    ),
                    player_position=Position(x=100, y=100, z=0, zone_id='zone_new'),
                    desired_count=1,
                    max_count=1,
                    world_prompt='test',
                    force_regenerate=True,
                )
            )
        self.assertTrue(resp.generated)

        updated = get_current_save(session_id)
        self.assertEqual([z.zone_id for z in updated.map_snapshot.zones], ['zone_new'])
        self.assertEqual(sorted({z.zone_id for z in updated.area_snapshot.zones}), ['zone_new'])
        self.assertEqual(updated.area_snapshot.current_zone_id, 'zone_new')
        self.assertEqual(updated.area_snapshot.current_sub_zone_id, 'sub_zone_new_1')
        self.assertNotIn('npc_old', [r.role_id for r in updated.role_pool])
        self.assertTrue(all((r.zone_id == 'zone_new') for r in updated.role_pool))

    def test_ai_generate_zones_accepts_nested_zone_payload_and_partial_count(self) -> None:
        config = ChatConfig(
            version='1.0.0',
            openai_api_key='sk-test',
            model='gpt-4.1-mini',
            stream=False,
            temperature=0.8,
            max_tokens=256,
            gm_prompt='test',
        )
        content = json.dumps(
            {
                'map': {
                    'zones': [
                        {
                            'name': '港埠区',
                            'zone_type': 'coast',
                            'size': 'small',
                            'radius_m': 120,
                            'x': 30,
                            'y': 40,
                            'description': '一片靠海的小港埠。',
                            'tags': ['port'],
                            'sub_zones': [
                                {'name': '码头', 'offset_x': 10, 'offset_y': 0, 'offset_z': 0, 'description': '停靠船只'},
                                {'name': '仓储区', 'offset_x': -20, 'offset_y': 15, 'offset_z': 0, 'description': '堆放货物'},
                                {'name': '鱼市', 'offset_x': 15, 'offset_y': -18, 'offset_z': 0, 'description': '清晨喧闹'},
                            ],
                        }
                    ]
                }
            },
            ensure_ascii=False,
        )
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34),
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: fake_response))
        )

        with patch('app.services.world_service.create_sync_client', return_value=fake_client):
            zones = _ai_generate_zones(
                'sess_nested_zone_payload',
                Position(x=0, y=0, z=0, zone_id='zone_0_0_0'),
                2,
                '沿海贸易小镇',
                config,
            )

        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0].name, '港埠区')
        self.assertEqual(zones[0].zone_type, 'coast')

    def test_generate_regions_selects_sub_zone_closest_to_zone_center(self) -> None:
        session_id = 'sess_generate_current_sub_zone'
        clear_current_save(session_id)
        generated_zone = Zone(
            zone_id='zone_center_pick',
            name='新城区',
            x=120,
            y=60,
            z=0,
            description='new',
            tags=['new'],
            sub_zones=[
                ZoneSubZoneSeed(name='远街', offset_x=90, offset_y=0, offset_z=0, description='far'),
                ZoneSubZoneSeed(name='中心广场', offset_x=5, offset_y=5, offset_z=0, description='near'),
                ZoneSubZoneSeed(name='另一端', offset_x=-80, offset_y=-20, offset_z=0, description='far2'),
            ],
        )

        with patch('app.services.world_service._ai_generate_zones', return_value=[generated_zone]):
            generate_regions(
                RegionGenerateRequest(
                    session_id=session_id,
                    config=ChatConfig(
                        version='1.0.0',
                        openai_api_key='sk-test',
                        model='gpt-4.1-mini',
                        stream=False,
                        temperature=0.8,
                        max_tokens=256,
                        gm_prompt='test',
                    ),
                    player_position=Position(x=120, y=60, z=0, zone_id='zone_center_pick'),
                    desired_count=1,
                    max_count=1,
                    world_prompt='test',
                    force_regenerate=True,
                )
            )

        updated = get_current_save(session_id)
        self.assertEqual(updated.area_snapshot.current_zone_id, 'zone_center_pick')
        self.assertEqual(updated.area_snapshot.current_sub_zone_id, 'sub_zone_center_pick_2')

    def test_get_area_current_backfills_missing_current_sub_zone(self) -> None:
        session_id = 'sess_backfill_current_sub_zone'
        self._seed_area(session_id)
        save = get_current_save(session_id)
        save.area_snapshot.current_sub_zone_id = None
        save_current(save)

        response = get_area_current(session_id)

        self.assertEqual(response.area_snapshot.current_zone_id, 'zone_a')
        self.assertEqual(response.area_snapshot.current_sub_zone_id, 'sub_a_1')

    def test_move_to_zone_selects_default_current_sub_zone(self) -> None:
        session_id = 'sess_move_zone_current_sub_zone'
        save = clear_current_save(session_id)
        save.session_id = session_id
        save.map_snapshot.player_position = Position(x=0, y=0, z=0, zone_id='zone_from')
        save.player_runtime_data.current_position = Position(x=0, y=0, z=0, zone_id='zone_from')
        save.map_snapshot.zones = [
            Zone(
                zone_id='zone_from',
                name='出发地',
                x=0,
                y=0,
                z=0,
                description='from',
                tags=['from'],
                sub_zones=[ZoneSubZoneSeed(name='起点', offset_x=0, offset_y=0, offset_z=0, description='start')],
            ),
            Zone(
                zone_id='zone_to',
                name='目的地',
                x=300,
                y=0,
                z=0,
                description='to',
                tags=['to'],
                sub_zones=[
                    ZoneSubZoneSeed(name='远侧', offset_x=120, offset_y=0, offset_z=0, description='far'),
                    ZoneSubZoneSeed(name='中心口', offset_x=8, offset_y=0, offset_z=0, description='near'),
                ],
            ),
        ]
        from app.services.world_service import save_current

        save_current(save)

        response = move_to_zone(
            MoveRequest(
                session_id=session_id,
                from_zone_id='zone_from',
                to_zone_id='zone_to',
                player_name='Player',
            )
        )

        self.assertEqual(response.new_position.zone_id, 'zone_to')
        updated = get_current_save(session_id)
        self.assertEqual(updated.area_snapshot.current_zone_id, 'zone_to')
        self.assertEqual(updated.area_snapshot.current_sub_zone_id, 'sub_zone_to_2')


if __name__ == '__main__':
    unittest.main()
