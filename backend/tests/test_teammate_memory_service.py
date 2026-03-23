import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.storage import storage_state
from app.models.schemas import (
    ChatConfig,
    NpcDialogueEntry,
    NpcPrivateChatMemoryEntry,
    NpcRoleCard,
    PlayerStaticData,
    TeamMember,
    TeamPrivateChatMemoryGenerateRequest,
)
from app.services.teammate_memory_service import (
    TeammatePrivateChatMemoryError,
    TeammatePrivateChatMemoryGenerationError,
    build_private_chat_memory_context,
    generate_teammate_private_chat_memory,
)
from app.services.world_service import clear_current_save, get_current_save, save_current


def _fake_completion_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
    )


class _FakeSyncClient:
    def __init__(self, content: str) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: _fake_completion_response(content)))


class TeammateMemoryServiceTests(unittest.TestCase):
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

    @staticmethod
    def _config() -> ChatConfig:
        return ChatConfig(
            provider="openai",
            api_key="test-key",
            model="test-model",
            stream=False,
            gm_prompt="You are a GM.",
        )

    def _seed_save(self, session_id: str, *, teammate: bool = True) -> None:
        save = clear_current_save(session_id)
        save.player_static_data.name = "布雷泽"
        save.player_static_data.player_id = "player_1"
        role = NpcRoleCard(
            role_id="npc_team_1",
            name="艾琳",
            zone_id="zone_1",
            sub_zone_id="sub_1",
            profile=PlayerStaticData(role_type="npc"),
            dialogue_logs=[
                NpcDialogueEntry(
                    id="dlg_1",
                    speaker="player",
                    speaker_role_id="player_1",
                    speaker_name="布雷泽",
                    context_kind="private_chat",
                    content="等会公开场合帮我盯住左边。",
                    world_time_text="1024-03-14 09:10",
                    world_time={"year": 1024, "month": 3, "day": 14, "hour": 9, "minute": 10},
                ),
                NpcDialogueEntry(
                    id="dlg_2",
                    speaker="npc",
                    speaker_role_id="npc_team_1",
                    speaker_name="艾琳",
                    context_kind="private_chat",
                    content="行，我先替你看住那边。",
                    world_time_text="1024-03-14 09:11",
                    world_time={"year": 1024, "month": 3, "day": 14, "hour": 9, "minute": 11},
                ),
                NpcDialogueEntry(
                    id="dlg_public",
                    speaker="npc",
                    speaker_role_id="npc_team_1",
                    speaker_name="艾琳",
                    context_kind="public_reaction",
                    content="她在公开场合点了点头。",
                    world_time_text="1024-03-14 09:12",
                    world_time={"year": 1024, "month": 3, "day": 14, "hour": 9, "minute": 12},
                ),
            ],
        )
        save.role_pool = [role]
        if teammate:
            save.team_state.members = [
                TeamMember(
                    role_id="npc_team_1",
                    name="艾琳",
                    affinity=62,
                    trust=58,
                )
            ]
        save_current(save)

    def test_generate_teammate_private_chat_memory_writes_summary(self) -> None:
        session_id = "sess_teammate_memory_ok"
        self._seed_save(session_id)
        payload = TeamPrivateChatMemoryGenerateRequest(
            session_id=session_id,
            npc_role_id="npc_team_1",
            source_dialogue_ids=["dlg_1", "dlg_2"],
            config=self._config(),
        )

        with patch("app.services.teammate_memory_service.create_sync_client", return_value=_FakeSyncClient('{"summary":"我得先替他盯住左边，别让人从那侧逼近。"}')):
            response = generate_teammate_private_chat_memory(payload)

        self.assertFalse(response.deduped_existing)
        self.assertEqual(response.memory.source_dialogue_ids, ["dlg_1", "dlg_2"])
        self.assertEqual(response.memory.summary, "我得先替他盯住左边，别让人从那侧逼近。")
        updated = get_current_save(session_id)
        self.assertEqual(len(updated.role_pool[0].private_chat_memories), 1)

    def test_generate_teammate_private_chat_memory_reuses_existing_entry(self) -> None:
        session_id = "sess_teammate_memory_dedupe"
        self._seed_save(session_id)
        payload = TeamPrivateChatMemoryGenerateRequest(
            session_id=session_id,
            npc_role_id="npc_team_1",
            source_dialogue_ids=["dlg_1", "dlg_2"],
            config=self._config(),
        )

        with patch("app.services.teammate_memory_service.create_sync_client", return_value=_FakeSyncClient('{"summary":"我记住了这件事。"}')):
            first = generate_teammate_private_chat_memory(payload)
            second = generate_teammate_private_chat_memory(payload)

        self.assertFalse(first.deduped_existing)
        self.assertTrue(second.deduped_existing)
        self.assertEqual(first.memory.memory_id, second.memory.memory_id)
        updated = get_current_save(session_id)
        self.assertEqual(len(updated.role_pool[0].private_chat_memories), 1)

    def test_generate_teammate_private_chat_memory_rejects_non_teammate(self) -> None:
        session_id = "sess_teammate_memory_not_member"
        self._seed_save(session_id, teammate=False)
        payload = TeamPrivateChatMemoryGenerateRequest(
            session_id=session_id,
            npc_role_id="npc_team_1",
            source_dialogue_ids=["dlg_1", "dlg_2"],
            config=self._config(),
        )

        with self.assertRaises(TeammatePrivateChatMemoryError):
            generate_teammate_private_chat_memory(payload)

    def test_generate_teammate_private_chat_memory_failure_writes_no_fallback(self) -> None:
        session_id = "sess_teammate_memory_fail"
        self._seed_save(session_id)
        payload = TeamPrivateChatMemoryGenerateRequest(
            session_id=session_id,
            npc_role_id="npc_team_1",
            source_dialogue_ids=["dlg_1", "dlg_2"],
            config=self._config(),
        )

        with patch("app.services.teammate_memory_service.create_sync_client", side_effect=RuntimeError("boom")):
            with self.assertRaises(TeammatePrivateChatMemoryGenerationError):
                generate_teammate_private_chat_memory(payload)

        updated = get_current_save(session_id)
        self.assertEqual(updated.role_pool[0].private_chat_memories, [])

    def test_build_private_chat_memory_context_returns_latest_twelve_summaries_only(self) -> None:
        role = NpcRoleCard(
            role_id="npc_team_1",
            name="艾琳",
            zone_id="zone_1",
            sub_zone_id="sub_1",
            profile=PlayerStaticData(role_type="npc"),
            private_chat_memories=[
                NpcPrivateChatMemoryEntry(
                    memory_id=f"mem_{index}",
                    world_time_text=f"1024-03-14 09:{index:02d}",
                    world_time={"minute": index},
                    summary=f"摘要{index}",
                    source_dialogue_ids=[f"dlg_{index}"],
                )
                for index in range(15)
            ],
        )

        payload = json.loads(build_private_chat_memory_context(role))

        self.assertEqual(len(payload), 12)
        self.assertEqual(payload[0]["summary"], "摘要14")
        self.assertEqual(payload[-1]["summary"], "摘要3")

