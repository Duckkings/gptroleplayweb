import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.schemas import ChatConfig, MainTurnSegment
from app.services.ai_adapter import resolve_structured_capability_profile
from app.services.structured_segment_service import (
    StructuredReplyFieldStreamParser,
    stream_main_turn_segment,
)


class StructuredCapabilityProfileTests(unittest.TestCase):
    def test_resolve_structured_capability_profile_by_provider(self) -> None:
        self.assertEqual(resolve_structured_capability_profile("openai", "gpt-5"), "openai_schema_stream")
        self.assertEqual(resolve_structured_capability_profile("deepseek", "deepseek-chat"), "deepseek_json_two_phase")
        self.assertEqual(resolve_structured_capability_profile("gemini", "gemini-2.5-flash"), "gemini_native_schema_stream")


class SegmentSchemaTests(unittest.TestCase):
    def test_main_turn_segment_requires_reaction_when_awaiting(self) -> None:
        with self.assertRaises(ValueError):
            MainTurnSegment.model_validate(
                {
                    "reply_text": "她抬手了。",
                    "public_actor_updates": [],
                    "public_round_resolution": "",
                    "encounter_update": {},
                    "segment_status": "awaiting_reaction",
                }
            )

    def test_reply_field_parser_emits_incremental_text(self) -> None:
        parser = StructuredReplyFieldStreamParser()
        self.assertEqual(parser.feed({"reply_text": ""}), "")
        self.assertEqual(parser.feed({"reply_text": "第一句"}), "第一句")
        self.assertEqual(parser.feed({"reply_text": "第一句第二句"}), "第二句")


class DeepSeekTwoPhaseTests(unittest.TestCase):
    def test_deepseek_two_phase_streams_reply_text(self) -> None:
        config = ChatConfig(
            provider="deepseek",
            api_key="sk-test",
            model="deepseek-chat",
            stream=True,
            gm_prompt="test",
        )
        fake_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "reply_text": "她抬手朝你打来。",
                                "public_actor_updates": [],
                                "public_round_resolution": "",
                                "encounter_update": {},
                                "player_reaction_check": {
                                    "source_kind": "npc_action",
                                    "source_actor_id": "npc_1",
                                    "source_actor_name": "醉汉",
                                    "source_label": "醉汉",
                                    "trigger_summary": "醉汉猛地朝你甩来一巴掌。",
                                    "threatened_consequence": "你可能被打中并陷入被动。",
                                    "ability_used": "dexterity",
                                    "dc": 12,
                                    "check_task": "躲开迎面打来的巴掌",
                                    "success_hint": "你及时偏头。",
                                    "failure_hint": "你被狠狠扇中。",
                                    "critical_success_hint": "",
                                    "critical_failure_hint": "",
                                },
                                "segment_status": "awaiting_reaction",
                            },
                            ensure_ascii=False,
                        )
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
        )
        emitted: list[str] = []

        async def run_case() -> None:
            with patch("app.services.structured_segment_service.create_async_client", return_value=fake_client):
                result = await stream_main_turn_segment(
                    config=config,
                    messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "user"}],
                    emit_reply_delta=lambda piece: _collect_piece(emitted, piece),
                    check_cancelled=None,
                )
            self.assertEqual(result.provider_path, "deepseek_json_two_phase")
            self.assertTrue(result.synthetic_stream)
            self.assertEqual(result.segment.reply_text, "她抬手朝你打来。")
            self.assertEqual("".join(emitted), "她抬手朝你打来。")
            self.assertEqual(result.usage.input_tokens, 11)
            self.assertEqual(result.usage.output_tokens, 22)
            self.assertEqual(result.segment.segment_status, "awaiting_reaction")

        async def _collect_piece(buffer: list[str], piece: str) -> None:
            buffer.append(piece)

        asyncio.run(run_case())

