import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.prompt_keys import PromptKeys, REQUIRED_PROMPT_KEYS
from app.core.prompt_table import prompt_table
from app.core.storage import storage_state
from types import SimpleNamespace

from app.models.schemas import ChatConfig, NpcChatRequest, NpcRoleCard, PlayerStaticData
from app.services.world_service import clear_current_save, npc_chat, save_current


class PromptRegistryTests(unittest.TestCase):
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

    def test_prompt_registry_required_keys_present(self) -> None:
        self.assertEqual(prompt_table.require_keys(REQUIRED_PROMPT_KEYS), [])

    def test_npc_chat_uses_v2_prompt_key(self) -> None:
        sid = "sess_prompt_npc_chat"
        save = clear_current_save(sid)
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_prompt",
                name="Prompt NPC",
                profile=PlayerStaticData(role_type="npc"),
            )
        ]
        save_current(save)

        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"action_reaction":"他抬眼看向你。","speech_reply":"我在。","relation_tag":"met"}'))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: fake_response)))

        with patch("app.services.world_service.prompt_table.render", wraps=prompt_table.render) as mocked_render:
            with patch("app.services.world_service.OpenAI", return_value=fake_client):
                npc_chat(
                    NpcChatRequest(
                        session_id=sid,
                        npc_role_id="npc_prompt",
                        player_message="你好",
                        config=ChatConfig(openai_api_key="test-key", model="test-model", gm_prompt="gm", stream=False),
                    )
                )

        rendered_keys = [call.args[0] for call in mocked_render.call_args_list if call.args]
        self.assertIn(PromptKeys.NPC_CHAT_USER, rendered_keys)

    def test_npc_chat_model_response_is_not_overwritten_by_fallback(self) -> None:
        sid = "sess_prompt_npc_chat_no_fallback_override"
        save = clear_current_save(sid)
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_prompt",
                name="Prompt NPC",
                profile=PlayerStaticData(role_type="npc"),
            )
        ]
        save_current(save)

        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"action_reaction":"他只是抬眼看着你。","speech_reply":"我在听。","relation_tag":"met"}'))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: fake_response)))

        with patch("app.services.world_service.OpenAI", return_value=fake_client):
            response = npc_chat(
                NpcChatRequest(
                    session_id=sid,
                    npc_role_id="npc_prompt",
                    player_message="你有什么想去的地方吗",
                    config=ChatConfig(openai_api_key="test-key", model="test-model", gm_prompt="gm", stream=False),
                )
            )

        self.assertEqual(response.action_reaction, "他只是抬眼看着你。")
        self.assertEqual(response.speech_reply, "我在听。")
        self.assertNotIn("旧地图", response.reply)
        self.assertNotIn("如果由我选", response.reply)


if __name__ == "__main__":
    unittest.main()
