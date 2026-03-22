from __future__ import annotations

from app.models.schemas import CharacterBuildBasicInfo


PORTRAIT_BASE_PROMPT = (
    "single character portrait, transparent background if supported; otherwise plain solid white background only, "
    "no scene, no environment, no extra characters, no cropped body, no watermark, no text, no logo, "
    "768x1344 vertical composition, semi-realistic full body in frame, feet visible, head not cropped, "
    "centered character, no extra props beyond the character's equipped gear"
)


def build_portrait_generation_prompt(prompt: str, basic_info: CharacterBuildBasicInfo | None = None) -> str:
    info = basic_info or CharacterBuildBasicInfo()
    sections: list[str] = []
    basics: list[str] = []

    if info.name.strip():
        basics.append(f"name: {info.name.strip()}")
    if info.race.strip():
        basics.append(f"race: {info.race.strip()}")
    if info.age > 0:
        basics.append(f"age: {info.age}")
    if info.height_cm > 0:
        basics.append(f"height_cm: {info.height_cm}")
    if info.body_type.strip():
        basics.append(f"body_type: {info.body_type.strip()}")
    if basics:
        sections.append("character basics: " + ", ".join(basics))

    prompt_text = str(prompt or "").strip()
    if prompt_text:
        sections.append(prompt_text)

    normalized_prompt = prompt_text.lower()
    if PORTRAIT_BASE_PROMPT.lower() not in normalized_prompt:
        sections.append(PORTRAIT_BASE_PROMPT)

    return "\n".join(section for section in sections if section).strip()
