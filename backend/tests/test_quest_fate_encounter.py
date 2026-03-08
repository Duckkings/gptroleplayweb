import tempfile
import unittest
from pathlib import Path

from app.core.storage import _save_bundle_dir, read_json, storage_state
from app.models.schemas import (
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    Coord3D,
    EncounterActRequest,
    EncounterCheckRequest,
    EncounterPresentRequest,
    FateEvaluateRequest,
    FateGenerateRequest,
    NpcRoleCard,
    PlayerStaticData,
    QuestActionRequest,
    QuestDraft,
    QuestEvaluateAllRequest,
    QuestObjective,
    QuestPublishRequest,
    RoleRelation,
)
from app.services.encounter_service import act_on_encounter, check_for_encounter, present_encounter
from app.services.fate_service import evaluate_fate_state, generate_fate
from app.services.quest_service import accept_quest, evaluate_all_quests, publish_quest, reject_quest
from app.services.world_service import clear_current_save, get_current_save, save_current


class QuestFateEncounterTests(unittest.TestCase):
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

    def _seed_context(self, session_id: str) -> None:
        save = clear_current_save(session_id)
        save.area_snapshot = AreaSnapshot(
            zones=[
                AreaZone(
                    zone_id='zone_town',
                    name='晨雾镇',
                    center=Coord3D(x=0, y=0, z=0),
                    sub_zone_ids=['sub_zone_town_1'],
                )
            ],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id='sub_zone_town_1',
                    zone_id='zone_town',
                    name='工会大厅',
                    coord=Coord3D(x=0, y=0, z=0),
                    description='工会大厅',
                )
            ],
            current_zone_id='zone_town',
            current_sub_zone_id='sub_zone_town_1',
            clock=save.area_snapshot.clock,
        )
        save.role_pool = [
            NpcRoleCard(
                role_id='npc_clerk',
                name='工会前台',
                zone_id='zone_town',
                sub_zone_id='sub_zone_town_1',
                profile=PlayerStaticData(role_type='npc'),
            )
        ]
        save_current(save)

    def test_save_bundle_contains_new_state_parts(self) -> None:
        sid = 'sess_bundle_new_parts'
        save = clear_current_save(sid)
        save_current(save)

        bundle_dir = _save_bundle_dir(storage_state.save_path)
        manifest = read_json(bundle_dir / 'manifest.json')
        parts = manifest.get('parts', {})

        self.assertIn('quest_state', parts)
        self.assertIn('encounter_state', parts)
        self.assertIn('fate_state', parts)
        self.assertTrue((bundle_dir / 'quest_state.json').exists())
        self.assertTrue((bundle_dir / 'encounter_state.json').exists())
        self.assertTrue((bundle_dir / 'fate_state.json').exists())

    def test_generate_fate_creates_pending_fate_quest(self) -> None:
        sid = 'sess_generate_fate'
        self._seed_context(sid)

        resp = generate_fate(FateGenerateRequest(session_id=sid))
        self.assertTrue(resp.generated)

        save = get_current_save(sid)
        self.assertIsNotNone(save.fate_state.current_fate)
        pending_fate_quests = [quest for quest in save.quest_state.quests if quest.source == 'fate' and quest.status == 'pending_offer']
        self.assertEqual(len(pending_fate_quests), 1)
        self.assertEqual(pending_fate_quests[0].offer_mode, 'accept_only')

    def test_fate_quest_reject_is_forbidden(self) -> None:
        sid = 'sess_fate_reject'
        self._seed_context(sid)
        generate_fate(FateGenerateRequest(session_id=sid))
        save = get_current_save(sid)
        fate_quest = next(quest for quest in save.quest_state.quests if quest.source == 'fate')

        with self.assertRaises(ValueError):
            reject_quest(sid, fate_quest.quest_id)

    def test_phase_two_unlocks_after_phase_one_completion(self) -> None:
        sid = 'sess_fate_progress'
        self._seed_context(sid)
        generate_fate(FateGenerateRequest(session_id=sid))
        save = get_current_save(sid)
        quest = next(item for item in save.quest_state.quests if item.source == 'fate')
        accept_quest(sid, quest.quest_id)

        save = get_current_save(sid)
        save.role_pool[0].relations.append(RoleRelation(target_role_id=save.player_static_data.player_id, relation_tag='met', note='已接触'))
        save_current(save)

        evaluate_all_quests(QuestEvaluateAllRequest(session_id=sid))
        evaluate_fate_state(FateEvaluateRequest(session_id=sid))

        updated = get_current_save(sid)
        current_fate = updated.fate_state.current_fate
        self.assertIsNotNone(current_fate)
        phase_two = next(phase for phase in current_fate.phases if phase.index == 2)
        self.assertEqual(phase_two.status, 'quest_offered')
        self.assertIsNotNone(phase_two.bound_quest_id)

    def test_resolve_encounter_quest_completes_and_logs(self) -> None:
        sid = 'sess_encounter_chain'
        self._seed_context(sid)

        published = publish_quest(
            QuestPublishRequest(
                session_id=sid,
                quest=QuestDraft(
                    source='normal',
                    offer_mode='accept_reject',
                    title='调查异常',
                    description='处理当前地区的异常遭遇。',
                    objectives=[
                        QuestObjective(
                            objective_id='obj_resolve',
                            kind='resolve_encounter',
                            title='解决异常',
                            description='完成一次异常遭遇。',
                            target_ref={'encounter_type': 'anomaly'},
                        )
                    ],
                ),
            )
        )
        accept_quest(sid, published.quest_id)

        check = check_for_encounter(EncounterCheckRequest(session_id=sid, trigger_kind='quest_rule'))
        self.assertTrue(check.generated)
        self.assertIsNotNone(check.encounter)
        encounter_id = check.encounter_id or ''

        present_encounter(encounter_id, EncounterPresentRequest(session_id=sid))
        result = act_on_encounter(
            encounter_id,
            EncounterActRequest(session_id=sid, player_prompt='我先稳定心神，靠近并解决异象核心。'),
        )
        self.assertEqual(result.status, 'resolved')

        updated = get_current_save(sid)
        quest = next(item for item in updated.quest_state.quests if item.quest_id == published.quest_id)
        self.assertEqual(quest.status, 'completed')
        self.assertTrue(any(log.kind == 'encounter_resolution_text' for log in updated.game_logs))


if __name__ == '__main__':
    unittest.main()
