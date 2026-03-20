import unittest

from app.services.ai_protocol_contract_service import (
    AI_CONFIG_REQUIRED,
    AiProtocolContractError,
    EnumContractField,
    render_enum_pool_text,
    require_ai_config,
    validate_enum_fields,
)
from app.services.public_turn_target_context_service import build_targeted_actor_text


class AiProtocolContractServiceTests(unittest.TestCase):
    def test_require_ai_config_raises_when_missing(self) -> None:
        with self.assertRaises(AiProtocolContractError) as ctx:
            require_ai_config(None)
        self.assertEqual(ctx.exception.code, AI_CONFIG_REQUIRED)

    def test_validate_enum_fields_rejects_unknown_ids(self) -> None:
        violations = validate_enum_fields(
            {"reaction_tone": "警告"},
            [EnumContractField(field_path="reaction_tone", allowed_ids=("supportive", "warning", "hostile"))],
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].field_path, "reaction_tone")
        self.assertEqual(violations[0].invalid_value, "警告")
        self.assertEqual(violations[0].reason, "not_in_allowed_ids")

    def test_render_enum_pool_text_lists_stable_ids(self) -> None:
        text = render_enum_pool_text(
            [
                EnumContractField(field_path="reaction_tone", allowed_ids=("supportive", "warning", "hostile")),
                EnumContractField(field_path="response_mode", allowed_ids=("speech", "action")),
            ]
        )
        self.assertIn("reaction_tone=supportive|warning|hostile", text)
        self.assertIn("response_mode=speech|action", text)

    def test_build_targeted_actor_text_with_targets(self) -> None:
        targeted = build_targeted_actor_text(
            actor_name="守卫",
            action_text="按住闹事者",
            speech_text="别再往前了。",
            action_target_name="闹事者",
            speech_target_name="玩家",
        )
        self.assertEqual(targeted.action_text_for_ai, "守卫对闹事者的行为：按住闹事者")
        self.assertEqual(targeted.speech_text_for_ai, "守卫对玩家说：别再往前了。")
        self.assertIn("守卫对闹事者的行为：按住闹事者", targeted.combined_text_for_ai)
        self.assertIn("守卫对玩家说：别再往前了。", targeted.combined_text_for_ai)

    def test_build_targeted_actor_text_without_targets(self) -> None:
        targeted = build_targeted_actor_text(
            actor_name="玩家",
            action_text="整理背包",
            speech_text="先等等。",
            action_target_name="",
            speech_target_name="",
        )
        self.assertEqual(targeted.action_text_for_ai, "玩家自己的行为：整理背包")
        self.assertEqual(targeted.speech_text_for_ai, "玩家说：先等等。")


if __name__ == "__main__":
    unittest.main()
