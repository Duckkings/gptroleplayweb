import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
    NpcRoleCard,
    EncounterRejoinRequest,
    EncounterTemporaryNpc,
    EncounterTerminationCondition,
)
from app.services.encounter_service import (
    _sanitize_temporary_npcs,
    _text_is_too_vague,
    act_on_encounter,
    advance_active_encounter_from_main_chat_in_save,
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

    def _chat_config(self) -> ChatConfig:
        return ChatConfig(openai_api_key="test-key", model="test-model", stream=False, gm_prompt="gm")

    def _fake_client(self, content: str):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response)))

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

        fake_client = self._fake_client(
            '{"type":"event","title":"异响","description":"广场附近传来可疑异动。","scene_summary":"广场开始紧张起来。","termination_conditions":[{"kind":"target_resolved","description":"查明异动来源。"}],"tags":["odd"]}'
        )
        with patch("app.services.encounter_service.create_sync_client", return_value=fake_client):
            response = check_for_encounter(
                EncounterCheckRequest(session_id=sid, trigger_kind="debug_forced", config=self._chat_config())
            )

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
            actor_name="Player",
            actor_kind="player",
            action_type="check",
            requires_check=True,
            ability_used="dexterity",
            ability_modifier=2,
            dc=10,
            check_task="从遭遇中脱身",
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
        fake_client = self._fake_client(
            '{"reply":"现场在玩家离开后继续变化。","scene_summary":"威胁仍在缓慢扩散。","termination_updates":[],"world_pushes":[],"actor_updates":[]}'
        )
        with patch("app.services.encounter_runtime_v2.create_sync_client", return_value=fake_client):
            advanced = advance_active_encounter_in_save(
                updated,
                session_id=sid,
                minutes_elapsed=5,
                config=self._chat_config(),
            )
        self.assertIsNotNone(advanced)
        assert advanced is not None
        self.assertEqual(advanced.background_tick_count, 1)

    def test_rejoin_requires_return_to_origin_sub_zone(self) -> None:
        sid = "sess_encounter_rejoin"
        self._seed_context(sid)
        save = get_current_save(sid)
        save.area_snapshot.zones[0].sub_zone_ids.append("sub_other")
        save.area_snapshot.sub_zones.append(
            AreaSubZone(
                sub_zone_id="sub_other",
                zone_id="zone_town",
                name="Alley",
                coord=Coord3D(x=5, y=0, z=0),
                description="Back alley",
            )
        )
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

    def test_main_chat_escape_requires_action_check(self) -> None:
        sid = "sess_encounter_main_chat_escape_check"
        self._seed_context(sid)
        save = get_current_save(sid)
        encounter = EncounterEntry(
            encounter_id="enc_escape_gate",
            type="event",
            status="active",
            title="Escape Gate",
            description="The threat presses in.",
            zone_id="zone_town",
            sub_zone_id="sub_town_1",
            player_presence="engaged",
            termination_conditions=[EncounterTerminationCondition(condition_id="cond_escape", kind="player_escapes", description="Player escapes")],
        )
        save.encounter_state.encounters = [encounter]
        save.encounter_state.active_encounter_id = encounter.encounter_id

        action_result = ActionCheckResponse(
            session_id=sid,
            actor_role_id="player_001",
            actor_name="Player",
            actor_kind="player",
            action_type="check",
            requires_check=True,
            ability_used="dexterity",
            ability_modifier=2,
            dc=10,
            check_task="脱离遭遇",
            dice_roll=4,
            total_score=6,
            success=False,
            critical="none",
            time_spent_min=1,
            narrative="未能脱离。",
            applied_effects=[],
            relation_tag_suggestion=None,
        )

        save_current(save)
        with patch("app.services.world_service.action_check", return_value=action_result) as mocked:
            events = advance_active_encounter_from_main_chat_in_save(
                save,
                session_id=sid,
                player_text="我要离开这里",
                gm_narration="你试图从现场抽身。",
                time_spent_min=1,
                config=None,
            )

        mocked.assert_called_once()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "encounter_progress")
        self.assertEqual(events[0].metadata.get("requires_check"), True)
        self.assertEqual(events[0].metadata.get("escape_success"), False)
        self.assertEqual(save.encounter_state.encounters[0].player_presence, "engaged")
        self.assertEqual(save.encounter_state.encounters[0].status, "active")

    def test_background_tick_writes_actor_steps_and_updates_locations(self) -> None:
        sid = "sess_encounter_background_runtime"
        self._seed_context(sid)
        save = get_current_save(sid)
        save.role_pool.append(NpcRoleCard(role_id="npc_guide", name="Guide", zone_id="zone_town", sub_zone_id="sub_town_1"))
        encounter = EncounterEntry(
            encounter_id="enc_background",
            type="event",
            status="escaped",
            title="Backstage Encounter",
            description="The encounter keeps moving without the player.",
            zone_id="zone_town",
            sub_zone_id="sub_town_1",
            player_presence="away",
            temporary_npcs=[
                EncounterTemporaryNpc(
                    encounter_npc_id="temp_watcher",
                    name="Watcher",
                    title="Watcher",
                    description="Keeps eyes on the trail.",
                    speaking_style="calm",
                    agenda="watch the trail",
                    state="active",
                    zone_id="zone_town",
                    sub_zone_id="sub_town_1",
                )
            ],
            termination_conditions=[EncounterTerminationCondition(condition_id="cond_goal", kind="target_resolved", description="Find the clue")],
        )
        save.encounter_state.encounters = [encounter]
        save.encounter_state.active_encounter_id = encounter.encounter_id

        class _FakeResponse:
            def __init__(self) -> None:
                self.choices = [
                    type(
                        "Choice",
                        (),
                        {
                            "message": type(
                                "Message",
                                (),
                                {
                                    "content": '{"reply":"The background situation keeps changing.","scene_summary":"The clue has shifted toward East Fringe / Stone Heap.","termination_updates":[],"step_kind":"background_tick","world_pushes":[{"push_kind":"new_clue","title":"Fresh clue","detail":"A new trace appears near the stone heap.","opened_window":"Return there to rejoin quickly.","pressure_note":"Rivals may arrive first.","situation_delta_hint":0,"location_target":{"zone_name":"East Fringe","zone_description":"A broken stone field just outside the inn.","zone_type_hint":"village","sub_zone_name":"Stone Heap","sub_zone_description":"Fresh traces hide between loose rocks.","reason":"The clue relocates here.","move_encounter_focus":true,"move_actor_ids":[]}}],"actor_updates":[{"actor_id":"npc_guide","actor_type":"npc","actor_name":"Guide","action_summary":"Guide heads to the new clue first.","impact_summary":"He drags the encounter focus toward the new clue site.","move_to_zone_name":"East Fringe","move_to_sub_zone_name":"Stone Heap"},{"actor_id":"temp_watcher","actor_type":"encounter_temp_npc","actor_name":"Watcher","action_summary":"Watcher follows and guards the perimeter.","impact_summary":"The new scene gains a cautious lookout.","move_to_zone_name":"East Fringe","move_to_sub_zone_name":"Stone Heap"}]}'
                                },
                            )()
                        },
                    )
                ]

        fake_client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": type("Completions", (), {"create": lambda *args, **kwargs: _FakeResponse()})()})()},
        )()
        config = ChatConfig(openai_api_key="test-key", model="test-model", stream=False, gm_prompt="gm")

        with patch("app.services.encounter_runtime_v2.create_sync_client", return_value=fake_client), patch(
            "app.services.world_service._ai_generate_encounter_location_content",
            return_value={
                "zone_name": "East Fringe",
                "zone_description": "A broken stone field just outside the inn.",
                "zone_type": "village",
                "zone_size": "small",
                "zone_radius_m": 120,
                "zone_tags": ["encounter_generated", "clue_site", "village"],
                "sub_zone_seeds": [
                    {
                        "name": "Stone Heap",
                        "description": "Fresh traces hide between loose rocks.",
                        "offset_x": 0,
                        "offset_y": 0,
                        "offset_z": 0,
                        "interactions": [{"name": "Search the stones", "type": "scene", "status": "ready"}],
                    },
                    {"name": "Path Mouth", "description": "A narrow path leading toward the village edge.", "offset_x": 18, "offset_y": -12, "offset_z": 0, "interactions": []},
                    {"name": "Broken Branch", "description": "Snapped branches scatter across the mud.", "offset_x": -16, "offset_y": 14, "offset_z": 0, "interactions": []},
                ],
                "target_sub_zone_name": "Stone Heap",
                "target_sub_zone_description": "Fresh traces hide between loose rocks.",
                "target_interactions": [{"name": "Search the stones", "type": "scene", "status": "ready"}],
            },
        ) as mocked_ai:
            advanced = advance_active_encounter_in_save(save, session_id=sid, minutes_elapsed=12, config=config)

        self.assertIsNotNone(advanced)
        assert advanced is not None
        mocked_ai.assert_called_once()
        self.assertTrue(any(step.kind == "npc_reaction" for step in advanced.steps))
        self.assertTrue(any(step.kind == "temp_npc_action" for step in advanced.steps))
        self.assertTrue(any(step.kind == "world_push" for step in advanced.steps))
        self.assertEqual(advanced.steps[-1].kind, "background_tick")
        npc_step = next(step for step in advanced.steps if step.kind == "npc_reaction")
        self.assertTrue(npc_step.metadata.get("moved_to_label"))
        self.assertTrue(npc_step.metadata.get("impact_summary"))
        role = next(item for item in save.role_pool if item.role_id == "npc_guide")
        self.assertEqual(role.zone_id, advanced.zone_id)
        self.assertEqual(role.sub_zone_id, advanced.sub_zone_id)
        self.assertEqual(advanced.temporary_npcs[0].zone_id, advanced.zone_id)
        self.assertEqual(advanced.temporary_npcs[0].sub_zone_id, advanced.sub_zone_id)

    def test_rejoin_uses_updated_encounter_location_after_background_tick(self) -> None:
        sid = "sess_encounter_rejoin_updated"
        self._seed_context(sid)
        save = get_current_save(sid)
        encounter = EncounterEntry(
            encounter_id="enc_rejoin_updated",
            type="event",
            status="escaped",
            title="Moving Encounter",
            description="The encounter relocates in the background.",
            zone_id="zone_town",
            sub_zone_id="sub_town_1",
            player_presence="away",
            termination_conditions=[EncounterTerminationCondition(condition_id="cond_goal", kind="target_resolved", description="Resolve it")],
        )
        save.encounter_state.encounters = [encounter]
        save.encounter_state.active_encounter_id = encounter.encounter_id

        class _FakeResponse:
            def __init__(self) -> None:
                self.choices = [
                    type(
                        "Choice",
                        (),
                        {
                            "message": type(
                                "Message",
                                (),
                                {
                                    "content": '{"reply":"The encounter shifts to a new place.","scene_summary":"The hotspot is no longer at the old scene.","termination_updates":[],"step_kind":"background_tick","world_pushes":[{"push_kind":"new_clue","title":"Shift","detail":"The hotspot has moved to East Fringe / Stone Heap.","opened_window":"Return there to rejoin.","pressure_note":"","situation_delta_hint":0,"location_target":{"zone_name":"East Fringe","zone_description":"A new hotspot beyond the tavern road.","zone_type_hint":"village","sub_zone_name":"Stone Heap","sub_zone_description":"The encounter has shifted to this stone heap.","reason":"Encounter migration","move_encounter_focus":true,"move_actor_ids":[]}}],"actor_updates":[]}'
                                },
                            )()
                        },
                    )
                ]

        fake_client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": type("Completions", (), {"create": lambda *args, **kwargs: _FakeResponse()})()})()},
        )()
        config = ChatConfig(openai_api_key="test-key", model="test-model", stream=False, gm_prompt="gm")

        with patch("app.services.encounter_runtime_v2.create_sync_client", return_value=fake_client), patch(
            "app.services.world_service._ai_generate_encounter_location_content",
            return_value={
                "zone_name": "East Fringe",
                "zone_description": "A new hotspot beyond the tavern road.",
                "zone_type": "village",
                "zone_size": "small",
                "zone_radius_m": 120,
                "zone_tags": ["encounter_generated", "clue_site", "village"],
                "sub_zone_seeds": [
                    {
                        "name": "Stone Heap",
                        "description": "The encounter has shifted to this stone heap.",
                        "offset_x": 0,
                        "offset_y": 0,
                        "offset_z": 0,
                        "interactions": [{"name": "Inspect the heap", "type": "scene", "status": "ready"}],
                    },
                    {"name": "Side Path", "description": "A side path points toward the new hotspot.", "offset_x": 20, "offset_y": -10, "offset_z": 0, "interactions": []},
                    {"name": "Shield Rock", "description": "Footprints overlap beside a low protective boulder.", "offset_x": -22, "offset_y": 16, "offset_z": 0, "interactions": []},
                ],
                "target_sub_zone_name": "Stone Heap",
                "target_sub_zone_description": "The encounter has shifted to this stone heap.",
                "target_interactions": [{"name": "Inspect the heap", "type": "scene", "status": "ready"}],
            },
        ) as mocked_ai:
            advance_active_encounter_in_save(save, session_id=sid, minutes_elapsed=10, config=config)

        mocked_ai.assert_called_once()
        save_current(save)
        with self.assertRaises(ValueError):
            rejoin_encounter(encounter.encounter_id, EncounterRejoinRequest(session_id=sid))

        updated = get_current_save(sid)
        updated.area_snapshot.current_zone_id = updated.encounter_state.encounters[0].zone_id
        updated.area_snapshot.current_sub_zone_id = updated.encounter_state.encounters[0].sub_zone_id
        save_current(updated)

        result = rejoin_encounter(encounter.encounter_id, EncounterRejoinRequest(session_id=sid))
        self.assertEqual(result.status, "active")

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
        fake_client = self._fake_client(
            '{"type":"event","title":"Strange Noise","description":"A suspicious sound echoes near the square.","scene_summary":"The square grows tense.","termination_conditions":[{"kind":"time_elapsed","description":"Time passes."}],"tags":["odd"]}'
        )

        with patch("app.services.encounter_service.create_sync_client", return_value=fake_client):
            response = check_for_encounter(
                EncounterCheckRequest(session_id=sid, trigger_kind="debug_forced", config=self._chat_config())
            )

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

        with patch("app.services.encounter_runtime_v2.create_sync_client", return_value=fake_client):
            result = act_on_encounter(
                encounter.encounter_id,
                EncounterActRequest(session_id=sid, player_prompt="我压低脚步，靠近巷口观察。", config=config),
            )

        self.assertRegex(result.reply, r"[\u4e00-\u9fff]")
        self.assertRegex(result.encounter.scene_summary, r"[\u4e00-\u9fff]")

    def test_main_chat_advances_active_encounter_and_returns_scene_event(self) -> None:
        sid = "sess_encounter_main_chat_progress"
        self._seed_context(sid)
        save = get_current_save(sid)
        encounter = EncounterEntry(
            encounter_id="enc_main_chat",
            type="event",
            status="active",
            title="Main Chat Clash",
            description="Trouble erupts in the square.",
            zone_id="zone_town",
            sub_zone_id="sub_town_1",
            player_presence="engaged",
            scene_summary="The square is unstable.",
            termination_conditions=[
                EncounterTerminationCondition(condition_id="cond_goal", kind="target_resolved", description="Resolve it")
            ],
        )
        save.encounter_state.encounters = [encounter]
        save.encounter_state.active_encounter_id = encounter.encounter_id

        with patch(
            "app.services.encounter_service._ai_resolve_encounter",
            return_value={
                "reply": "The clash pushes closer to the player.",
                "scene_summary": "The clash closes in.",
                "step_kind": "gm_update",
                "termination_updates": [],
            },
        ):
            events = advance_active_encounter_from_main_chat_in_save(
                save,
                session_id=sid,
                player_text='{"input_type":"player_intent_v1","action_description":"I brace myself","speech_description":"Hold the line"}',
                gm_narration="Dust kicks up across the square.",
                time_spent_min=2,
                config=None,
            )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].kind, "encounter_situation_update")
        self.assertEqual(events[1].kind, "encounter_progress")
        self.assertEqual(save.encounter_state.encounters[0].latest_outcome_summary, "The clash pushes closer to the player.")
        self.assertEqual(save.encounter_state.encounters[0].scene_summary, "The clash closes in.")
        self.assertEqual(save.encounter_state.encounters[0].steps[-1].kind, "gm_update")

    def test_main_chat_can_resolve_active_encounter(self) -> None:
        sid = "sess_encounter_main_chat_resolution"
        self._seed_context(sid)
        save = get_current_save(sid)
        encounter = EncounterEntry(
            encounter_id="enc_main_chat_resolve",
            type="event",
            status="active",
            title="Resolved by Main Chat",
            description="One decisive exchange remains.",
            zone_id="zone_town",
            sub_zone_id="sub_town_1",
            player_presence="engaged",
            scene_summary="The final beat is here.",
            termination_conditions=[
                EncounterTerminationCondition(condition_id="cond_goal", kind="target_resolved", description="Resolve it")
            ],
        )
        save.encounter_state.encounters = [encounter]
        save.encounter_state.active_encounter_id = encounter.encounter_id

        with patch(
            "app.services.encounter_service._ai_resolve_encounter",
            return_value={
                "reply": "The last obstacle gives way.",
                "scene_summary": "The scene settles.",
                "step_kind": "resolution",
                "termination_updates": [{"condition_index": 0, "satisfied": True}],
            },
        ):
            events = advance_active_encounter_from_main_chat_in_save(
                save,
                session_id=sid,
                player_text='{"input_type":"player_intent_v1","action_description":"I finish the fight","speech_description":"It is over"}',
                gm_narration="The final exchange lands.",
                time_spent_min=2,
                config=None,
            )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].kind, "encounter_situation_update")
        self.assertEqual(events[1].kind, "encounter_resolution")
        self.assertEqual(save.encounter_state.encounters[0].status, "resolved")
        self.assertIsNone(save.encounter_state.active_encounter_id)

    def test_main_chat_passive_turn_appends_observe_step(self) -> None:
        sid = "sess_encounter_main_chat_passive"
        self._seed_context(sid)
        save = get_current_save(sid)
        encounter = EncounterEntry(
            encounter_id="enc_main_chat_passive",
            type="event",
            status="active",
            title="Passive Watch",
            description="The scene keeps moving without direct player action.",
            zone_id="zone_town",
            sub_zone_id="sub_town_1",
            player_presence="engaged",
            scene_summary="The crowd is unsettled.",
            termination_conditions=[
                EncounterTerminationCondition(condition_id="cond_goal", kind="target_resolved", description="Resolve it")
            ],
        )
        save.encounter_state.encounters = [encounter]
        save.encounter_state.active_encounter_id = encounter.encounter_id

        with patch(
            "app.services.encounter_service._ai_resolve_encounter",
            return_value={
                "reply": "The crowd shifts on its own while the player watches.",
                "scene_summary": "The tension keeps building.",
                "step_kind": "gm_update",
                "termination_updates": [],
            },
        ):
            events = advance_active_encounter_from_main_chat_in_save(
                save,
                session_id=sid,
                player_text='{"input_type":"player_intent_v1","passive_turn":true,"passive_mode":"observe"}',
                gm_narration="The player holds back and watches the square.",
                time_spent_min=1,
                config=None,
            )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].kind, "encounter_situation_update")
        self.assertEqual(events[1].kind, "encounter_progress")
        self.assertEqual(save.encounter_state.encounters[0].steps[-2].kind, "player_action")
        self.assertEqual(save.encounter_state.encounters[0].steps[-2].content, "【玩家旁观】玩家本轮选择观察与等待，不主动行动。")
        self.assertEqual(save.encounter_state.history[-1].player_prompt, "【玩家旁观】玩家本轮选择观察与等待，不主动行动。")


    def test_sanitize_temporary_npcs_limits_and_deduplicates(self) -> None:
        items = _sanitize_temporary_npcs(
            [
                {"name": "管理员", "title": "图书馆管理员", "description": "守在倒下的书架旁", "speaking_style": "急促", "agenda": "收拢禁书"},
                {"name": "管理员", "title": "重复角色", "description": "重复", "speaking_style": "短促", "agenda": "重复"},
                {"name": "学徒", "title": "抄写学徒", "description": "躲在楼梯口后面", "speaking_style": "发抖", "agenda": "护住账本"},
            ]
        )
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item.encounter_npc_id.startswith("encnpc_") for item in items))
        self.assertEqual(items[0].name, "管理员")
        self.assertEqual(items[1].name, "学徒")

    def test_text_is_too_vague_rejects_abstract_reply(self) -> None:
        self.assertTrue(_text_is_too_vague("NPC 发现了危险。"))
        self.assertFalse(_text_is_too_vague("管理员发现左侧书架的上层木板已经松动，正朝楼梯口砸下来。"))

    def test_generated_encounter_can_include_temporary_npcs(self) -> None:
        sid = "sess_encounter_generate_temp_npc"
        self._seed_context(sid)
        save = get_current_save(sid)
        save.encounter_state.debug_force_trigger = True
        save_current(save)
        config = ChatConfig(openai_api_key="test-key", model="test-model", stream=False, gm_prompt="gm")

        class _FakeResponse:
            def __init__(self) -> None:
                self.choices = [
                    type(
                        "Choice",
                        (),
                        {
                            "message": type(
                                "Message",
                                (),
                                {
                                    "content": '{"type":"event","title":"图书馆异动","description":"旧书架后面传出纸页摩擦声。","temporary_npcs":[{"name":"管理员","title":"图书馆管理员","description":"她正护住掉落的账册。","speaking_style":"急促","agenda":"先把散页收回柜台后方"}],"scene_summary":"管理员正拦在倾斜的书架前。","termination_conditions":[{"kind":"target_resolved","description":"稳住书架并找出异动来源。"}],"tags":["library"]}'
                                },
                            )()
                        },
                    )
                ]

        fake_client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": type("Completions", (), {"create": lambda *args, **kwargs: _FakeResponse()})()})()},
        )()

        with patch("app.services.encounter_service.create_sync_client", return_value=fake_client):
            response = check_for_encounter(EncounterCheckRequest(session_id=sid, trigger_kind="debug_forced", config=config))

        self.assertTrue(response.generated)
        self.assertIsNotNone(response.encounter)
        assert response.encounter is not None
        self.assertEqual(len(response.encounter.temporary_npcs), 1)
        self.assertEqual(response.encounter.temporary_npcs[0].name, "管理员")
        self.assertFalse(any(role.name == "管理员" for role in get_current_save(sid).role_pool))

if __name__ == "__main__":
    unittest.main()
