import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.storage import _save_bundle_dir, read_json, storage_state
from app.models.schemas import (
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    ChatConfig,
    Coord3D,
    FateGenerateRequest,
    NpcRoleCard,
    PlayerStaticData,
    Position,
    QuestDraft,
    QuestObjective,
    QuestPublishRequest,
    RegionGenerateRequest,
    WorldClock,
    Zone,
    ZoneSubZoneSeed,
)
from app.services.consistency_service import build_npc_knowledge_snapshot
from app.services.encounter_service import _ai_generate_encounter_guarded
from app.services.fate_service import generate_fate
from app.services.quest_service import _ai_generate_quest_draft_guarded, accept_quest, publish_quest
from app.services.world_service import clear_current_save, generate_regions, get_current_save, save_current


class ConsistencyServiceTests(unittest.TestCase):
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
                    zone_id="zone_old",
                    name="Old Town",
                    center=Coord3D(x=0, y=0, z=0),
                    sub_zone_ids=["sub_old_1"],
                ),
                AreaZone(
                    zone_id="zone_remote",
                    name="Remote Camp",
                    center=Coord3D(x=500, y=0, z=0),
                    sub_zone_ids=["sub_remote_1"],
                ),
            ],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_old_1",
                    zone_id="zone_old",
                    name="Guild Hall",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="Guild hall",
                ),
                AreaSubZone(
                    sub_zone_id="sub_remote_1",
                    zone_id="zone_remote",
                    name="Watch Post",
                    coord=Coord3D(x=500, y=0, z=0),
                    description="Watch post",
                ),
            ],
            current_zone_id="zone_old",
            current_sub_zone_id="sub_old_1",
            clock=WorldClock(calendar="fantasy_default", year=1024, month=3, day=14, hour=9, minute=30),
        )
        save.map_snapshot.player_position = Position(x=0, y=0, z=0, zone_id="zone_old")
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_local",
                name="Local Clerk",
                zone_id="zone_old",
                sub_zone_id="sub_old_1",
                profile=PlayerStaticData(role_type="npc"),
            ),
            NpcRoleCard(
                role_id="npc_remote",
                name="Remote Scout",
                zone_id="zone_remote",
                sub_zone_id="sub_remote_1",
                profile=PlayerStaticData(role_type="npc"),
            ),
        ]
        save_current(save)

    def _test_config(self) -> ChatConfig:
        return ChatConfig(
            version="1.0.0",
            openai_api_key="sk-test",
            model="gpt-4.1-mini",
            stream=False,
            temperature=0.4,
            max_tokens=256,
            gm_prompt="test",
        )

    def _mock_client(self, payload: dict[str, object]) -> SimpleNamespace:
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))]
        )
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))

    def test_save_bundle_contains_world_state_part(self) -> None:
        sid = "sess_world_bundle"
        save = clear_current_save(sid)
        save_current(save)

        bundle_dir = _save_bundle_dir(storage_state.save_path)
        manifest = read_json(bundle_dir / "manifest.json")
        parts = manifest.get("parts", {})

        self.assertIn("world_state", parts)
        self.assertTrue((bundle_dir / "world_state.json").exists())

    def test_force_regenerate_invalidates_stale_story_content(self) -> None:
        sid = "sess_invalidation"
        self._seed_context(sid)
        generate_fate(FateGenerateRequest(session_id=sid))
        save = get_current_save(sid)
        fate_quest = next(item for item in save.quest_state.quests if item.source == "fate")
        accept_quest(sid, fate_quest.quest_id)

        normal_quest = publish_quest(
            QuestPublishRequest(
                session_id=sid,
                quest=QuestDraft(
                    source="normal",
                    offer_mode="accept_reject",
                    title="Talk to local clerk",
                    description="Ask the local clerk about the town.",
                    zone_id="zone_old",
                    sub_zone_id="sub_old_1",
                    objectives=[
                        QuestObjective(
                            objective_id="obj_local",
                            kind="talk_to_npc",
                            title="Talk to clerk",
                            description="Talk to the local clerk",
                            target_ref={"npc_role_id": "npc_local"},
                        )
                    ],
                ),
            )
        )
        accept_quest(sid, normal_quest.quest_id)

        new_zone = Zone(
            zone_id="zone_new",
            name="New Frontier",
            x=100,
            y=100,
            z=0,
            description="Freshly generated",
            tags=["new"],
            sub_zones=[ZoneSubZoneSeed(name="New Hub", description="Fresh hub")],
        )
        with patch("app.services.world_service._ai_generate_zones", return_value=[new_zone]):
            generate_regions(
                RegionGenerateRequest(
                    session_id=sid,
                    config=ChatConfig(
                        version="1.0.0",
                        openai_api_key="sk-test",
                        model="gpt-4.1-mini",
                        stream=False,
                        temperature=0.8,
                        max_tokens=128,
                        gm_prompt="test",
                    ),
                    player_position=Position(x=100, y=100, z=0, zone_id="zone_new"),
                    desired_count=1,
                    max_count=1,
                    world_prompt="test",
                    force_regenerate=True,
                )
            )

        updated = get_current_save(sid)
        self.assertGreaterEqual(updated.world_state.world_revision, 2)
        self.assertGreaterEqual(updated.world_state.map_revision, 2)
        self.assertIsNone(updated.fate_state.current_fate)
        self.assertTrue(any(item.status == "superseded" for item in updated.fate_state.archive))
        stale_normal = next(item for item in updated.quest_state.quests if item.quest_id == normal_quest.quest_id)
        stale_fate = next(item for item in updated.quest_state.quests if item.quest_id == fate_quest.quest_id)
        self.assertEqual(stale_normal.status, "invalidated")
        self.assertEqual(stale_fate.status, "superseded")

    def test_npc_knowledge_snapshot_limits_remote_npcs(self) -> None:
        sid = "sess_knowledge"
        self._seed_context(sid)

        save = get_current_save(sid)
        snapshot = build_npc_knowledge_snapshot(save, "npc_local")

        self.assertEqual(snapshot.npc_role_id, "npc_local")
        self.assertNotIn("npc_remote", snapshot.known_local_npc_ids)
        self.assertIn("npc_remote", snapshot.forbidden_entity_ids)
        self.assertTrue(snapshot.response_rules)

    def test_ai_quest_guard_drops_unknown_npc_reference(self) -> None:
        sid = "sess_ai_quest_guard"
        self._seed_context(sid)
        save = get_current_save(sid)
        client = self._mock_client(
            {
                "title": "Ask the missing scout",
                "description": "Follow a rumor about a scout who is not here.",
                "issuer_role_id": "npc_remote",
                "objectives": [
                    {
                        "kind": "talk_to_npc",
                        "title": "Talk to remote scout",
                        "description": "Find and talk to the remote scout.",
                        "target_ref": {"npc_role_id": "npc_remote"},
                    }
                ],
                "rewards": [{"kind": "gold", "label": "Coins", "payload": {"amount": 10}}],
            }
        )

        with patch("app.services.quest_service.OpenAI", return_value=client):
            draft = _ai_generate_quest_draft_guarded(save, "normal", self._test_config())

        self.assertIsNotNone(draft)
        assert draft is not None
        self.assertIsNone(draft.issuer_role_id)
        self.assertEqual(draft.objectives, [])
        self.assertEqual(draft.metadata.get("entity_guard"), "allowed_ids")
        self.assertFalse(any(ref.entity_type == "npc" and ref.entity_id == "npc_remote" for ref in draft.entity_refs))

    def test_ai_encounter_guard_rejects_unknown_npc_id(self) -> None:
        sid = "sess_ai_encounter_guard"
        self._seed_context(sid)
        save = get_current_save(sid)
        client = self._mock_client(
            {
                "type": "npc",
                "title": "Remote scout appears",
                "description": "A scout from elsewhere approaches.",
                "npc_role_id": "npc_remote",
                "tags": ["npc", "mystery"],
            }
        )

        with patch("app.services.encounter_service.OpenAI", return_value=client):
            encounter = _ai_generate_encounter_guarded(save, "random_dialog", self._test_config())

        self.assertIsNone(encounter)


if __name__ == "__main__":
    unittest.main()
