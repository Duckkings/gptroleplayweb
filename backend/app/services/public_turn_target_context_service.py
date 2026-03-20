from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TargetedActorText:
    action_text_for_ai: str
    speech_text_for_ai: str
    combined_text_for_ai: str
    debug_context_payload: dict[str, Any]


def build_targeted_actor_text(
    *,
    actor_name: str,
    action_text: str,
    speech_text: str,
    action_target_name: str | None = None,
    speech_target_name: str | None = None,
) -> TargetedActorText:
    actor_label = " ".join(str(actor_name or "").split()).strip() or "角色"
    clean_action = " ".join(str(action_text or "").split()).strip()
    clean_speech = " ".join(str(speech_text or "").split()).strip()
    clean_action_target = " ".join(str(action_target_name or "").split()).strip()
    clean_speech_target = " ".join(str(speech_target_name or "").split()).strip()

    action_text_for_ai = ""
    if clean_action:
        if clean_action_target:
            action_text_for_ai = f"{actor_label}对{clean_action_target}的行为：{clean_action}"
        else:
            action_text_for_ai = f"{actor_label}自己的行为：{clean_action}"

    speech_text_for_ai = ""
    if clean_speech:
        if clean_speech_target:
            speech_text_for_ai = f"{actor_label}对{clean_speech_target}说：{clean_speech}"
        else:
            speech_text_for_ai = f"{actor_label}说：{clean_speech}"

    combined = "\n".join(part for part in (action_text_for_ai, speech_text_for_ai) if part).strip()
    return TargetedActorText(
        action_text_for_ai=action_text_for_ai,
        speech_text_for_ai=speech_text_for_ai,
        combined_text_for_ai=combined or f"{actor_label}暂时没有额外公开动作或对白。",
        debug_context_payload={
            "actor_name": actor_label,
            "action_text": clean_action,
            "speech_text": clean_speech,
            "action_target_name": clean_action_target or None,
            "speech_target_name": clean_speech_target or None,
            "action_text_for_ai": action_text_for_ai,
            "speech_text_for_ai": speech_text_for_ai,
            "combined_text_for_ai": combined or f"{actor_label}暂时没有额外公开动作或对白。",
        },
    )
