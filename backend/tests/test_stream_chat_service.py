import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.core.storage import storage_state
from app.core.user_context import get_current_user, set_current_user
from app.models.schemas import ActionCheckResponse, AreaSnapshot, AreaSubZone, ChatRequest, ChatConfig, Coord3D, EncounterCheckResponse, EncounterEntry, EncounterTerminationCondition, Message, NpcRoleCard, SceneEvent, TeamMember, ToolEvent, WorldClock
from app.services.stream_chat_service import StreamProtocolError, StreamingTurnParser, _execute_planned_tools, _main_turn_summary_from_scene_events, apply_structured_main_turn_bundle, run_main_turn_stream
from app.services.world_service import clear_current_save, get_current_save, save_current, save_transaction


class StreamingTurnParserTests(unittest.TestCase):
    def test_parser_emits_reply_and_parses_bundle_across_chunks(self) -> None:
        parser = StreamingTurnParser("turn_bundle")
        chunks = [
            "<rep",
            "ly>第一段",
            "第二段</reply><turn_b",
            'undle>{"ok":true,"count":2}</turn_bundle>',
        ]
        emitted: list[str] = []
        for chunk in chunks:
            emitted.extend(parser.feed(chunk))

        self.assertEqual("".join(emitted), "第一段第二段")
        self.assertEqual(parser.require_bundle(), {"ok": True, "count": 2})

    def test_parser_raises_for_invalid_bundle_json(self) -> None:
        parser = StreamingTurnParser("npc_bundle")
        parser.feed('<reply>ok</reply><npc_bundle>{"broken":</npc_bundle>')

        with self.assertRaises(StreamProtocolError):
            parser.require_bundle()

    def test_parser_tolerates_trailing_quote_after_bundle_json(self) -> None:
        parser = StreamingTurnParser("turn_bundle")
        parser.feed('<reply>ok</reply><turn_bundle>{"ok":true}"</turn_bundle>')

        self.assertEqual(parser.require_bundle(), {"ok": True})


class SaveTransactionTests(unittest.TestCase):
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

    def test_transaction_rollback_does_not_persist(self) -> None:
        original = get_current_save(default_session_id="sess_txn_rollback")
        original.player_static_data.name = "Original"
        save_current(original)

        with save_transaction("sess_txn_rollback"):
            working = get_current_save(default_session_id="sess_txn_rollback")
            working.player_static_data.name = "Discarded"
            save_current(working)

        reloaded = get_current_save(default_session_id="sess_txn_rollback")
        self.assertEqual(reloaded.player_static_data.name, "Original")

    def test_transaction_commit_persists_once(self) -> None:
        with save_transaction("sess_txn_commit") as txn:
            working = get_current_save(default_session_id="sess_txn_commit")
            working.player_static_data.name = "Committed"
            save_current(working)
            txn.commit()

        reloaded = get_current_save(default_session_id="sess_txn_commit")
        self.assertEqual(reloaded.player_static_data.name, "Committed")


class PlannedToolExecutionTests(unittest.TestCase):
    def test_failed_planned_tool_does_not_abort_turn(self) -> None:
        payload = ChatRequest(
            session_id="sess_planner_skip",
            messages=[Message(role="user", content="看看周围")],
            config=ChatConfig(api_key="sk-test", model="gpt-4.1-mini", stream=False, gm_prompt="test"),
        )
        planned_tools = [{"tool_name": "get_npc_knowledge", "args": {}}]

        async def run_case() -> None:
            with patch(
                "app.services.chat_service._handle_tool_call",
                new=AsyncMock(
                    return_value=(
                        {"role": "tool", "tool_call_id": "planner_1", "content": '{"ok":false,"error":"missing"}'},
                        ToolEvent(tool_name="get_npc_knowledge", ok=False, summary="npc_role_id is required"),
                    )
                ),
            ):
                events, results = await _execute_planned_tools(payload, planned_tools, emit=None)
            self.assertEqual(len(events), 1)
            self.assertFalse(events[0].ok)
            self.assertEqual(results[0]["result"]["error"], "npc_role_id is required")

        asyncio.run(run_case())

    def test_failed_turn_writes_latest_generation_log(self) -> None:
        payload = ChatRequest(
            session_id="sess_log_error",
            messages=[Message(role="assistant", content="no user message")],
            config=ChatConfig(api_key="sk-test", model="gpt-4.1-mini", stream=False, gm_prompt="test"),
        )

        async def run_case() -> None:
            with self.assertRaisesRegex(ValueError, "LAST_USER_MESSAGE_REQUIRED"):
                await run_main_turn_stream(payload, emit=None, is_cancelled=None)

        asyncio.run(run_case())
        log_path = Path(storage_state.save_path.parent) / "debug" / "latest-generation-log.json"
        payload_json = json.loads(log_path.read_text(encoding="utf-8"))
        self.assertEqual(payload_json["flow_kind"], "main_chat")
        self.assertEqual(payload_json["session_id"], "sess_log_error")
        self.assertEqual(payload_json["status"], "error")
        self.assertIn("LAST_USER_MESSAGE_REQUIRED", payload_json["error"]["message"])

    def test_apply_structured_bundle_falls_back_to_visible_local_actor(self) -> None:
        session_id = "sess_public_actor_fallback"
        save = clear_current_save(session_id)
        save.session_id = session_id
        save.area_snapshot = AreaSnapshot(
            current_zone_id="zone_a",
            current_sub_zone_id="sub_zone_a",
            clock=WorldClock(calendar="fantasy_default", year=1024, month=3, day=14, hour=9, minute=30),
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_zone_a",
                    zone_id="zone_a",
                    name="酒馆",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="当前子区块",
                    npcs=[],
                )
            ],
        )
        npc = NpcRoleCard(role_id="npc_1", name="川洛", zone_id="zone_a", sub_zone_id="sub_zone_a")
        teammate = NpcRoleCard(role_id="team_1", name="缇儿", zone_id="zone_a", sub_zone_id="sub_zone_a", state="in_team")
        save.role_pool = [npc, teammate]
        save.team_state.members = [
            TeamMember(
                role_id="team_1",
                name="缇儿",
                origin_zone_id="zone_a",
                origin_sub_zone_id="sub_zone_a",
                join_source="debug",
                is_debug=True,
            )
        ]
        save_current(save)

        bundle = {
            "public_actor_updates": [
                {
                    "actor_id": "npc_1",
                    "actor_type": "npc",
                    "action_reaction": "压低声音环顾四周。",
                    "speech_reply": "这里确实不对劲。",
                    "response_mode": "respond",
                    "target_label": "",
                    "specific_threat": "",
                    "needs_check": False,
                    "action_type": "check",
                    "planned_ability_used": "wisdom",
                    "planned_dc": 10,
                    "planned_time_spent_min": 1,
                    "planned_check_task": "",
                    "situation_delta_hint": 0,
                    "relation_delta_hint": 0,
                    "reputation_delta_hint": 0,
                }
            ],
            "public_round_resolution": "川洛也确认了现场异常。",
            "encounter_update": {},
        }

        with patch(
            "app.services.stream_chat_service.public_scene_runtime.candidate_rows",
            return_value=[{"actor_id": "team_1", "name": "缇儿", "actor_type": "team", "priority_reason": "test", "role": teammate}],
        ), patch(
            "app.services.stream_chat_service._fallback_public_actor_rows",
            return_value=[{"actor_id": "npc_1", "name": "川洛", "actor_type": "npc", "priority_reason": "fallback", "role": npc}],
        ), patch(
            "app.services.stream_chat_service.public_scene_legacy._append_actor_memory",
            return_value=None,
        ), patch(
            "app.services.stream_chat_service.public_scene_legacy._apply_actor_relation_delta",
            return_value=0,
        ), patch(
            "app.services.stream_chat_service.zone_metric_service.apply_zone_reputation_delta",
            return_value=(None, None),
        ), patch(
            "app.services.stream_chat_service.encounter_legacy.check_for_encounter",
            return_value=EncounterCheckResponse(),
        ), patch(
            "app.services.stream_chat_service.encounter_runtime.advance_active_encounter_in_save",
            return_value=None,
        ):
            events = apply_structured_main_turn_bundle(
                get_current_save(default_session_id=session_id),
                session_id=session_id,
                player_text="我检查地上的痕迹。",
                gm_narration="你发现了几处可疑足迹。",
                time_spent_min=1,
                bundle=bundle,
                config=None,
            )

        actor_events = [event for event in events if event.kind == "public_actor_action"]
        self.assertEqual(len(actor_events), 1)
        self.assertEqual(actor_events[0].actor_role_id, "npc_1")
        self.assertFalse(any(event.kind == "public_actor_resolution" for event in events))
        self.assertEqual(actor_events[0].metadata.get("affiliation_label"), "在场NPC")
        self.assertEqual(actor_events[0].metadata.get("check_result", {}).get("outcome_label"), "无需检定")
        round_event = next(event for event in events if event.kind == "public_round_resolution")
        self.assertNotIn("result_rows", round_event.metadata)
        self.assertNotIn("predicted_situation_value", round_event.metadata)
        self.assertNotIn("situation_value_before", round_event.metadata)
        self.assertNotIn("situation_value_after", round_event.metadata)

    def test_apply_structured_bundle_merges_check_result_into_public_actor_action(self) -> None:
        session_id = "sess_public_actor_check_merge"
        save = clear_current_save(session_id)
        save.session_id = session_id
        save.area_snapshot = AreaSnapshot(
            current_zone_id="zone_a",
            current_sub_zone_id="sub_zone_a",
            clock=WorldClock(calendar="fantasy_default", year=1024, month=3, day=14, hour=9, minute=30),
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_zone_a",
                    zone_id="zone_a",
                    name="酒馆",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="当前子区域",
                    npcs=[],
                )
            ],
        )
        npc = NpcRoleCard(role_id="npc_1", name="川洛", zone_id="zone_a", sub_zone_id="sub_zone_a")
        save.role_pool = [npc]
        save_current(save)

        bundle = {
            "public_actor_updates": [
                {
                    "actor_id": "npc_1",
                    "actor_type": "npc",
                    "action_reaction": "快步靠近桌边，翻找刚留下的痕迹。",
                    "speech_reply": "我先把线头找出来。",
                    "response_mode": "respond",
                    "target_label": "桌边痕迹",
                    "specific_threat": "线索随时会被踩乱",
                    "action_type": "check",
                    "planned_ability_used": "wisdom",
                    "planned_dc": 10,
                    "planned_time_spent_min": 1,
                    "planned_check_task": "检查桌边痕迹",
                    "situation_delta_hint": 2,
                    "relation_delta_hint": 0,
                    "reputation_delta_hint": 0,
                }
            ],
            "public_round_resolution": "川洛替你先把桌边最乱的地方稳住了。",
            "encounter_update": {},
        }

        action_result = ActionCheckResponse(
            session_id=session_id,
            actor_role_id="npc_1",
            actor_name="川洛",
            actor_kind="npc",
            action_type="check",
            requires_check=True,
            ability_used="wisdom",
            ability_modifier=4,
            dc=10,
            check_task="检查桌边痕迹",
            dice_roll=2,
            total_score=6,
            success=False,
            critical="none",
            time_spent_min=1,
            narrative="【检定】川洛未能及时压住桌边的混乱。",
            applied_effects=[],
            scene_events=[],
            relation_tag=None,
        )

        with patch(
            "app.services.stream_chat_service.public_scene_runtime.candidate_rows",
            return_value=[{"actor_id": "npc_1", "name": "川洛", "actor_type": "npc", "priority_reason": "test", "role": npc}],
        ), patch(
            "app.services.stream_chat_service._fallback_public_actor_rows",
            return_value=[],
        ), patch(
            "app.services.stream_chat_service.public_scene_legacy._append_actor_memory",
            return_value=None,
        ), patch(
            "app.services.stream_chat_service.public_scene_legacy._apply_actor_relation_delta",
            return_value=0,
        ), patch(
            "app.services.stream_chat_service.zone_metric_service.apply_zone_reputation_delta",
            return_value=(None, None),
        ), patch(
            "app.services.stream_chat_service.encounter_legacy.check_for_encounter",
            return_value=EncounterCheckResponse(),
        ), patch(
            "app.services.stream_chat_service.encounter_runtime.advance_active_encounter_in_save",
            return_value=None,
        ), patch(
            "app.services.stream_chat_service.world.action_check",
            return_value=action_result,
        ):
            events = apply_structured_main_turn_bundle(
                get_current_save(default_session_id=session_id),
                session_id=session_id,
                player_text="我让川洛先看看桌边的痕迹。",
                gm_narration="你示意川洛先检查桌边。",
                time_spent_min=1,
                bundle=bundle,
                config=None,
            )

        actor_event = next(event for event in events if event.kind == "public_actor_action")
        self.assertFalse(any(event.kind == "public_actor_resolution" for event in events))
        check_result = actor_event.metadata.get("check_result", {})
        self.assertEqual(check_result.get("requires_check"), True)
        self.assertEqual(check_result.get("ability_used"), "wisdom")
        self.assertEqual(check_result.get("ability_modifier"), 4)
        self.assertEqual(check_result.get("dice_roll"), 2)
        self.assertEqual(check_result.get("total_score"), 6)
        self.assertEqual(check_result.get("dc"), 10)
        self.assertEqual(check_result.get("outcome_label"), "失败")

        self.assertEqual(actor_event.metadata.get("situation_delta"), -2)

    def test_public_team_actor_updates_affinity_and_trust_metadata(self) -> None:
        session_id = "sess_public_team_relation"
        save = clear_current_save(session_id)
        save.session_id = session_id
        save.area_snapshot = AreaSnapshot(
            current_zone_id="zone_a",
            current_sub_zone_id="sub_zone_a",
            clock=WorldClock(calendar="fantasy_default", year=1024, month=3, day=14, hour=9, minute=30),
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_zone_a",
                    zone_id="zone_a",
                    name="酒馆",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="当前子区块",
                    npcs=[],
                )
            ],
        )
        teammate = NpcRoleCard(role_id="team_1", name="缨儿", zone_id="zone_a", sub_zone_id="sub_zone_a", state="in_team")
        save.role_pool = [teammate]
        save.team_state.members = [
            TeamMember(
                role_id="team_1",
                name="缨儿",
                origin_zone_id="zone_a",
                origin_sub_zone_id="sub_zone_a",
                affinity=42,
                trust=30,
                join_source="debug",
                is_debug=True,
            )
        ]
        save_current(save)

        bundle = {
            "public_actor_updates": [
                {
                    "actor_id": "team_1",
                    "actor_type": "team",
                    "action_reaction": "被公开羞辱后明显皱起了眉。",
                    "speech_reply": "你没必要当着这么多人这样说我。",
                    "response_mode": "respond",
                    "target_label": "",
                    "specific_threat": "",
                    "action_type": "check",
                    "planned_ability_used": "charisma",
                    "planned_dc": 10,
                    "planned_time_spent_min": 1,
                    "planned_check_task": "当众回应玩家的羞辱",
                    "situation_delta_hint": 0,
                    "relation_delta_hint": -3,
                    "reputation_delta_hint": 0,
                }
            ],
            "public_round_resolution": "缨儿被当众顶撞后，对玩家的态度明显冷了下来。",
            "encounter_update": {},
        }

        def apply_relation(*_args, **_kwargs):
            member = save.team_state.members[0]
            member.affinity = 36
            member.trust = 26
            return -3

        with patch(
            "app.services.stream_chat_service.public_scene_runtime.candidate_rows",
            return_value=[{"actor_id": "team_1", "name": "缨儿", "actor_type": "team", "priority_reason": "test", "role": teammate}],
        ), patch(
            "app.services.stream_chat_service._fallback_public_actor_rows",
            return_value=[],
        ), patch(
            "app.services.stream_chat_service.public_scene_legacy._append_actor_memory",
            return_value=None,
        ), patch(
            "app.services.stream_chat_service.public_scene_legacy._apply_actor_relation_delta",
            side_effect=apply_relation,
        ), patch(
            "app.services.stream_chat_service.zone_metric_service.apply_zone_reputation_delta",
            return_value=(None, None),
        ), patch(
            "app.services.stream_chat_service.encounter_legacy.check_for_encounter",
            return_value=EncounterCheckResponse(),
        ), patch(
            "app.services.stream_chat_service.encounter_runtime.advance_active_encounter_in_save",
            return_value=None,
        ):
            events = apply_structured_main_turn_bundle(
                save,
                session_id=session_id,
                player_text="我当众羞辱缨儿。",
                gm_narration="缨儿脸色一变。",
                time_spent_min=1,
                bundle=bundle,
                config=None,
            )

        actor_event = next(event for event in events if event.kind == "public_actor_action")
        self.assertEqual(actor_event.metadata.get("team_affinity_before"), 42)
        self.assertEqual(actor_event.metadata.get("team_affinity_after"), 36)
        self.assertEqual(actor_event.metadata.get("team_affinity_delta"), -6)
        self.assertEqual(actor_event.metadata.get("team_trust_before"), 30)
        self.assertEqual(actor_event.metadata.get("team_trust_after"), 26)
        self.assertEqual(actor_event.metadata.get("team_trust_delta"), -4)
        round_event = next(event for event in events if event.kind == "public_round_resolution")
        rows = round_event.metadata.get("team_relation_rows") or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "缨儿")
        self.assertEqual(rows[0]["affinity_after"], 36)
        self.assertTrue(any(item.trigger_kind == "public_turn" for item in save.team_state.reactions))

    def test_team_only_audience_suppresses_non_team_speech(self) -> None:
        session_id = "sess_public_team_scope"
        save = clear_current_save(session_id)
        save.session_id = session_id
        save.area_snapshot = AreaSnapshot(
            current_zone_id="zone_a",
            current_sub_zone_id="sub_zone_a",
            clock=WorldClock(calendar="fantasy_default", year=1024, month=3, day=14, hour=9, minute=30),
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_zone_a",
                    zone_id="zone_a",
                    name="酒馆",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="当前子区域",
                    npcs=[],
                )
            ],
        )
        npc = NpcRoleCard(role_id="npc_1", name="川洛", zone_id="zone_a", sub_zone_id="sub_zone_a")
        teammate = NpcRoleCard(role_id="team_1", name="缨儿", zone_id="zone_a", sub_zone_id="sub_zone_a", state="in_team")
        save.role_pool = [npc, teammate]
        save.team_state.members = [
            TeamMember(
                role_id="team_1",
                name="缨儿",
                origin_zone_id="zone_a",
                origin_sub_zone_id="sub_zone_a",
                join_source="debug",
                is_debug=True,
            )
        ]
        save_current(save)

        bundle = {
            "public_actor_updates": [
                {
                    "actor_id": "npc_1",
                    "actor_type": "npc",
                    "action_reaction": "抬头看了你们一眼，但没有靠近。",
                    "speech_reply": "我们这边最好先撤开。",
                    "response_mode": "respond",
                    "target_label": "",
                    "specific_threat": "",
                    "action_type": "check",
                    "planned_ability_used": "wisdom",
                    "planned_dc": 10,
                    "planned_time_spent_min": 1,
                    "planned_check_task": "",
                    "situation_delta_hint": 0,
                    "relation_delta_hint": 0,
                    "reputation_delta_hint": 0,
                }
            ],
            "public_round_resolution": "现场其他人暂时没有直接插话。",
            "encounter_update": {},
        }

        with patch(
            "app.services.stream_chat_service.public_scene_runtime.candidate_rows",
            return_value=[
                {"actor_id": "npc_1", "name": "川洛", "actor_type": "npc", "priority_reason": "test", "role": npc},
                {"actor_id": "team_1", "name": "缨儿", "actor_type": "team", "priority_reason": "test", "role": teammate},
            ],
        ), patch(
            "app.services.stream_chat_service._fallback_public_actor_rows",
            return_value=[],
        ), patch(
            "app.services.stream_chat_service.public_scene_legacy._append_actor_memory",
            return_value=None,
        ), patch(
            "app.services.stream_chat_service.public_scene_legacy._apply_actor_relation_delta",
            return_value=0,
        ), patch(
            "app.services.stream_chat_service.zone_metric_service.apply_zone_reputation_delta",
            return_value=(None, None),
        ), patch(
            "app.services.stream_chat_service.encounter_legacy.check_for_encounter",
            return_value=EncounterCheckResponse(),
        ), patch(
            "app.services.stream_chat_service.encounter_runtime.advance_active_encounter_in_save",
            return_value=None,
        ):
            events = apply_structured_main_turn_bundle(
                get_current_save(default_session_id=session_id),
                session_id=session_id,
                player_text="对缨儿说：你怎么看？",
                gm_narration="你把问题抛给了缨儿。",
                time_spent_min=1,
                bundle=bundle,
                config=None,
            )

        actor_event = next(event for event in events if event.kind == "public_actor_action")
        self.assertEqual(actor_event.actor_role_id, "npc_1")
        self.assertEqual(actor_event.metadata.get("response_mode"), "ignore")
        self.assertEqual(actor_event.metadata.get("speech_line"), "")

    def test_main_turn_summary_extracts_final_breakdown(self) -> None:
        summary = _main_turn_summary_from_scene_events(
            [
                SceneEvent(event_id="evt_round", kind="public_round_resolution", actor_name="GM", content="summary", metadata={}),
                SceneEvent(
                    event_id="evt_situation",
                    kind="encounter_situation_update",
                    actor_name="GM",
                    content="situation update",
                    metadata={
                        "situation_value_before": 51,
                        "player_situation_delta": 2,
                        "public_actor_situation_delta_total": 9,
                        "world_push_situation_delta_total": 5,
                        "turn_total_delta": 16,
                        "situation_value_after": 67,
                        "situation_value": 67,
                        "situation_delta": 16,
                    },
                ),
            ]
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary.player_situation_delta, 2)
        self.assertEqual(summary.public_actor_situation_delta_total, 9)
        self.assertEqual(summary.world_push_situation_delta_total, 5)
        self.assertEqual(summary.turn_total_delta, 16)
        self.assertEqual(summary.situation_value_before, 51)
        self.assertEqual(summary.situation_value_after, 67)

    def test_apply_structured_bundle_world_push_generates_missing_location(self) -> None:
        session_id = "sess_world_push_location"
        save = clear_current_save(session_id)
        save.session_id = session_id
        config = ChatConfig(openai_api_key="test-key", model="test-model", stream=False, gm_prompt="gm")
        save.area_snapshot = AreaSnapshot(
            current_zone_id="zone_a",
            current_sub_zone_id="sub_zone_a",
            clock=WorldClock(calendar="fantasy_default", year=1024, month=3, day=14, hour=9, minute=30),
            zones=[],
            sub_zones=[
                AreaSubZone(
                    sub_zone_id="sub_zone_a",
                    zone_id="zone_a",
                    name="Inn",
                    coord=Coord3D(x=0, y=0, z=0),
                    description="Current sub-zone",
                    npcs=[],
                )
            ],
        )
        save.encounter_state.encounters = [
            EncounterEntry(
                encounter_id="enc_loc",
                type="event",
                status="active",
                title="Shifting Clue",
                description="The clue needs a new scene location.",
                zone_id="zone_a",
                sub_zone_id="sub_zone_a",
                player_presence="engaged",
                termination_conditions=[EncounterTerminationCondition(condition_id="cond_goal", kind="target_resolved", description="Find the clue")],
            )
        ]
        save.encounter_state.active_encounter_id = "enc_loc"
        save_current(save)

        bundle = {
            "public_actor_updates": [],
            "public_round_resolution": "",
            "encounter_update": {
                "summary": "The clue points toward the east gate.",
                "situation_delta_hint": 2,
                "step_kind": "gm_update",
                "termination_updates": [],
                "world_pushes": [
                    {
                        "push_kind": "new_clue",
                        "title": "Fresh clue",
                        "detail": "A new trace appears near the east gate stone pile.",
                        "opened_window": "You can head there immediately.",
                        "pressure_note": "",
                        "situation_delta_hint": 3,
                        "location_target": {
                            "zone_name": "East Gate",
                            "zone_description": "A rough area just outside the inn.",
                            "zone_type_hint": "village",
                            "sub_zone_name": "Stone Pile",
                            "sub_zone_description": "The trace is hidden among scattered rocks.",
                            "reason": "The clue relocates here.",
                            "move_encounter_focus": True,
                            "move_actor_ids": [],
                        },
                    }
                ],
            },
        }

        with patch("app.services.stream_chat_service.zone_metric_service.apply_zone_reputation_delta", return_value=(None, None)), patch(
            "app.services.world_service._ai_generate_encounter_location_content",
            return_value={
                "zone_name": "East Gate",
                "zone_description": "A rough area just outside the inn.",
                "zone_type": "village",
                "zone_size": "small",
                "zone_radius_m": 120,
                "zone_tags": ["encounter_generated", "clue_site", "village"],
                "sub_zone_seeds": [
                    {
                        "name": "Stone Pile",
                        "description": "The trace is hidden among scattered rocks.",
                        "offset_x": 0,
                        "offset_y": 0,
                        "offset_z": 0,
                        "interactions": [{"name": "翻找碎石", "type": "scene", "status": "ready"}],
                    },
                    {
                        "name": "Watch Post",
                        "description": "A narrow overlook facing the gate.",
                        "offset_x": 24,
                        "offset_y": -12,
                        "offset_z": 0,
                        "interactions": [],
                    },
                    {
                        "name": "Cart Rut",
                        "description": "Wheel marks cut through damp soil.",
                        "offset_x": -20,
                        "offset_y": 18,
                        "offset_z": 0,
                        "interactions": [],
                    },
                ],
                "target_sub_zone_name": "Stone Pile",
                "target_sub_zone_description": "The trace is hidden among scattered rocks.",
                "target_interactions": [{"name": "翻找碎石", "type": "scene", "status": "ready"}],
            },
        ) as mocked_ai:
            events = apply_structured_main_turn_bundle(
                save,
                session_id=session_id,
                player_text="I check the new clue.",
                gm_narration="The scene points somewhere more specific.",
                time_spent_min=1,
                bundle=bundle,
                config=config,
            )

        updated = save
        encounter = updated.encounter_state.encounters[0]
        world_push_event = next(event for event in events if event.kind == "encounter_world_push")
        mocked_ai.assert_called_once()
        self.assertTrue(any(zone.name == "East Gate" for zone in updated.map_snapshot.zones))
        self.assertTrue(any(sub_zone.name == "Stone Pile" for sub_zone in updated.area_snapshot.sub_zones))
        target_sub_zone = next(sub_zone for sub_zone in updated.area_snapshot.sub_zones if sub_zone.name == "Stone Pile")
        self.assertTrue(any(item.name == "翻找碎石" for item in target_sub_zone.key_interactions))
        self.assertEqual(encounter.zone_id, world_push_event.metadata.get("target_zone_id"))
        self.assertEqual(encounter.sub_zone_id, world_push_event.metadata.get("target_sub_zone_id"))
        self.assertTrue(any(ref.entity_type == "sub_zone" and ref.entity_id == encounter.sub_zone_id for ref in encounter.entity_refs))


if __name__ == "__main__":
    unittest.main()
