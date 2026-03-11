from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import ceil
import random
from typing import Any

from openai import OpenAI

from app.core.prompt_keys import PromptKeys
from app.core.prompt_table import prompt_table
from app.models.schemas import (
    ActionCheckResponse,
    ChatConfig,
    EntityRef,
    EncounterActRequest,
    EncounterActResponse,
    EncounterCheckRequest,
    EncounterCheckResponse,
    EncounterDebugOverviewResponse,
    EncounterEntry,
    EncounterOutcomeChange,
    EncounterOutcomePackage,
    EncounterEscapeRequest,
    EncounterEscapeResponse,
    EncounterForceToggleRequest,
    EncounterForceToggleResponse,
    EncounterHistoryResponse,
    EncounterPendingResponse,
    EncounterPresentRequest,
    EncounterPresentResponse,
    EncounterRejoinRequest,
    EncounterRejoinResponse,
    EncounterResolution,
    EncounterState,
    EncounterStepEntry,
    EncounterTemporaryNpc,
    EncounterTerminationCondition,
    GameLogEntry,
    InventoryItem,
    RoleBuff,
)
from app.services.consistency_service import (
    build_entity_index,
    build_global_story_snapshot,
    ensure_world_state,
    extract_entity_refs_from_encounter,
    validate_entity_refs,
)
from app.services.ai_adapter import build_completion_options, create_sync_client
from app.services.world_service import _advance_clock, _default_world_clock, _new_scene_event, _parse_player_intent, get_current_save, save_current
from app.services.reputation_service import apply_sub_zone_reputation_delta, get_current_sub_zone_reputation


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"


def _append_game_log(save, session_id: str, kind: str, message: str, payload: dict[str, str | int | float | bool] | None = None) -> None:
    save.game_logs.append(
        GameLogEntry(
            id=_new_id("glog"),
            session_id=session_id,
            kind=kind,
            message=message,
            payload=payload or {},
        )
    )


def _touch_state(state: EncounterState) -> None:
    state.updated_at = _utc_now()


def _state(save) -> EncounterState:
    if save.encounter_state is None:
        save.encounter_state = EncounterState()
    return save.encounter_state


def _pending_entries(state: EncounterState) -> list[EncounterEntry]:
    entries: list[EncounterEntry] = []
    for encounter_id in state.pending_ids:
        found = next((item for item in state.encounters if item.encounter_id == encounter_id and item.status == "queued"), None)
        if found is not None:
            entries.append(found)
    return entries


def _find_encounter(state: EncounterState, encounter_id: str) -> EncounterEntry:
    encounter = next((item for item in state.encounters if item.encounter_id == encounter_id), None)
    if encounter is None:
        raise KeyError("ENCOUNTER_NOT_FOUND")
    return encounter


def _current_active_encounter(state: EncounterState) -> EncounterEntry | None:
    if not state.active_encounter_id:
        return None
    encounter = next((item for item in state.encounters if item.encounter_id == state.active_encounter_id), None)
    if encounter is None or encounter.status not in {"active", "escaped"}:
        return None
    return encounter


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, int(value)))


@dataclass(frozen=True)
class SituationAssessment:
    before_value: int
    delta: int
    after_value: int
    direction: str
    trend: str
    allowed_lexicon: tuple[str, ...]
    forbidden_lexicon: tuple[str, ...]


def _assess_situation_change(before_value: int, delta: int, after_value: int) -> SituationAssessment:
    before = _clamp(before_value, 0, 100)
    applied = int(delta)
    after = _clamp(after_value, 0, 100)
    if applied > 0:
        return SituationAssessment(
            before_value=before,
            delta=applied,
            after_value=after,
            direction="stabilize",
            trend="improving",
            allowed_lexicon=("稳住", "压住", "争取到空间", "局势更稳", "险情被控制"),
            forbidden_lexicon=("恶化", "更糟", "失控扩大", "逼近失控", "压力扩大", "险情扩散"),
        )
    if applied < 0:
        return SituationAssessment(
            before_value=before,
            delta=applied,
            after_value=after,
            direction="worsen",
            trend="worsening",
            allowed_lexicon=("恶化", "逼近失控", "压力扩大", "险情扩散"),
            forbidden_lexicon=("稳住", "压住", "局势更稳", "险情被控制", "争取到空间"),
        )
    return SituationAssessment(
        before_value=before,
        delta=0,
        after_value=after,
        direction="hold",
        trend="stable",
        allowed_lexicon=("暂时维持", "僵持", "未继续恶化", "未取得突破"),
        forbidden_lexicon=("恶化", "更糟", "失控扩大", "稳住", "压住", "局势更稳"),
    )


def _assessment_line(assessment: SituationAssessment) -> str:
    if assessment.direction == "stabilize":
        return f"局势值变为 {assessment.after_value}/100，本轮更稳，险情被压住。"
    if assessment.direction == "worsen":
        return f"局势值变为 {assessment.after_value}/100，局面正在恶化，压力继续扩大。"
    return f"局势值变为 {assessment.after_value}/100，现场暂时维持僵持，没有继续恶化，但也未取得突破。"


def _text_conflicts_with_assessment(text: str, assessment: SituationAssessment) -> bool:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return True
    return any(token in clean for token in assessment.forbidden_lexicon)


def _enforce_assessment_text(text: str, assessment: SituationAssessment, *, fallback_reason: str) -> str:
    clean = " ".join((text or "").split()).strip()
    if clean and not _text_conflicts_with_assessment(clean, assessment):
        return clean[:240]
    basis = fallback_reason.strip() or "现场局势发生了新的变化。"
    if assessment.direction == "stabilize":
        rebuilt = f"{basis} 这一步替现场争取到了更稳的空间，最危险的部分暂时被压住。"
    elif assessment.direction == "worsen":
        rebuilt = f"{basis} 这一步没能压住最直接的风险，现场压力继续扩大，局面朝更糟的方向滑去。"
    else:
        rebuilt = f"{basis} 现场暂时维持僵持，没有继续恶化，但也还没出现真正的突破口。"
    return rebuilt[:240]


def _encounter_actor_label(save, encounter: EncounterEntry, actor_role_id: str = "", actor_name: str = "") -> str:
    if actor_name:
        return actor_name
    if actor_role_id:
        role = next((item for item in save.role_pool if item.role_id == actor_role_id), None)
        if role is not None and role.name:
            return role.name
        temp_npc = next((item for item in getattr(encounter, "temporary_npcs", []) or [] if item.encounter_npc_id == actor_role_id), None)
        if temp_npc is not None and temp_npc.name:
            return temp_npc.name
    if encounter.npc_role_id:
        role = next((item for item in save.role_pool if item.role_id == encounter.npc_role_id), None)
        if role is not None and role.name:
            return role.name
    first_temp = next((item for item in getattr(encounter, "temporary_npcs", []) or [] if item.name), None)
    if first_temp is not None:
        return first_temp.name
    return "现场局势"

def _contains_concrete_marker(text: str) -> bool:
    concrete_tokens = [
        "书架",
        "书页",
        "管理员",
        "地板",
        "门",
        "窗",
        "符文",
        "影子",
        "楼梯",
        "桌",
        "柜",
        "走廊",
        "巷",
        "脚步",
        "木板",
        "锁",
        "火",
        "绳",
        "血",
        "石",
        "箱",
    ]
    return any(token in (text or "") for token in concrete_tokens)


def _text_is_too_vague(text: str) -> bool:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return True
    vague_tokens = ["危险", "异常", "变化", "局势", "紧张", "不安", "某种", "似乎", "仿佛", "威胁", "压力", "进展"]
    if any(token in clean for token in vague_tokens) and not _contains_concrete_marker(clean):
        return True
    return False


def _visible_participant_text(save, encounter: EncounterEntry) -> tuple[str, str]:
    team_members = [member.name for member in getattr(save.team_state, "members", []) if member.status == "active"]
    npc_names: list[str] = []
    if encounter.npc_role_id:
        role = next((item for item in save.role_pool if item.role_id == encounter.npc_role_id), None)
        if role is not None:
            npc_names.append(role.name)
    npc_names.extend(temp.name for temp in getattr(encounter, "temporary_npcs", []) or [] if temp.name)
    return (" / ".join(team_members) or "none", " / ".join(npc_names) or "none")


def _build_encounter_temp_npc(raw: dict[str, object], index: int) -> EncounterTemporaryNpc | None:
    name = _force_chinese_text(raw.get("name"), "", limit=24)
    if not name:
        return None
    title = _force_chinese_text(raw.get("title"), "", limit=40)
    description = _force_chinese_text(raw.get("description"), f"{name}卷入了眼前的遭遇。", limit=120)
    speaking_style = _force_chinese_text(raw.get("speaking_style"), "", limit=60)
    agenda = _force_chinese_text(raw.get("agenda"), f"{name}正试图处理眼前最危险的部分。", limit=80)
    return EncounterTemporaryNpc(
        encounter_npc_id=f"encnpc_{index + 1}_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        name=name,
        title=title,
        description=description,
        speaking_style=speaking_style,
        agenda=agenda,
        state="active",
    )


def _sanitize_temporary_npcs(raw_list: object) -> list[EncounterTemporaryNpc]:
    if not isinstance(raw_list, list):
        return []
    items: list[EncounterTemporaryNpc] = []
    seen_names: set[str] = set()
    for index, raw in enumerate(raw_list):
        if len(items) >= 2:
            break
        if not isinstance(raw, dict):
            continue
        built = _build_encounter_temp_npc(raw, index)
        if built is None or built.name in seen_names:
            continue
        seen_names.add(built.name)
        items.append(built)
    return items


def _check_bonus_from_result(action_result: ActionCheckResponse | None) -> int:
    if action_result is None:
        return 0
    if action_result.critical == "critical_success":
        return 8
    if action_result.critical == "critical_failure":
        return -8
    return 4 if action_result.success else -4


def _check_bonus_from_player_prompt(player_prompt: str) -> int:
    parsed = _parse_player_intent(player_prompt)
    action_check = parsed.get("action_check") if isinstance(parsed.get("action_check"), dict) else None
    if not isinstance(action_check, dict):
        return 0
    critical = str(action_check.get("critical") or "none")
    if critical == "critical_success":
        return 8
    if critical == "critical_failure":
        return -8
    return 4 if bool(action_check.get("success")) else -4


def _player_low_resources(save) -> bool:
    sheet = save.player_static_data.dnd5e_sheet
    hp_ratio = 1.0 if sheet.hit_points.maximum <= 0 else (sheet.hit_points.current / max(1, sheet.hit_points.maximum))
    stamina_ratio = 1.0 if sheet.stamina_maximum <= 0 else (sheet.stamina_current / max(1, sheet.stamina_maximum))
    return hp_ratio < 0.3 or stamina_ratio < 0.3


def _calculate_initial_situation_value(save, encounter: EncounterEntry) -> int:
    value = 50
    reputation = get_current_sub_zone_reputation(save, create=True)
    score = reputation.score if reputation is not None else 50
    if score >= 70:
        value += 10
    elif score <= 30:
        value -= 10
    tracked = next((item for item in save.quest_state.quests if item.status == "active" and item.is_tracked), None)
    if tracked is not None and (
        tracked.quest_id in encounter.related_quest_ids
        or (tracked.fate_phase_id and tracked.fate_phase_id in encounter.related_fate_phase_ids)
    ):
        value += 5
    current_fate = save.fate_state.current_fate
    if current_fate is not None and current_fate.current_phase_id and current_fate.current_phase_id in encounter.related_fate_phase_ids:
        value += 5
    if _player_low_resources(save):
        value -= 5
    if getattr(save.team_state, "members", []):
        value += 5
    return _clamp(value, 20, 80)


def _refresh_participants(save, encounter: EncounterEntry) -> None:
    participant_ids = [member.role_id for member in getattr(save.team_state, "members", [])]
    if encounter.npc_role_id and encounter.npc_role_id not in participant_ids:
        participant_ids.append(encounter.npc_role_id)
    for temp_npc in getattr(encounter, "temporary_npcs", []) or []:
        if temp_npc.encounter_npc_id not in participant_ids:
            participant_ids.append(temp_npc.encounter_npc_id)
    encounter.participant_role_ids = participant_ids


def _initialize_encounter_state(save, encounter: EncounterEntry) -> None:
    if encounter.presented_at is None:
        encounter.presented_at = _utc_now()
    encounter.situation_start_value = _calculate_initial_situation_value(save, encounter)
    encounter.situation_value = encounter.situation_start_value
    encounter.situation_trend = "stable"
    _refresh_participants(save, encounter)


def _situation_result(encounter: EncounterEntry) -> str:
    if encounter.situation_value >= 50:
        return "success"
    return "failure"


def _fallback_situation_delta(encounter: EncounterEntry, player_prompt: str) -> int:
    clean = (player_prompt or "").strip()
    positive_tokens = ["查清", "确认", "解决", "稳住", "保护", "帮忙", "观察", "谈判", "说服", "追上"]
    negative_tokens = ["逃跑", "失手", "激怒", "闹大", "攻击", "乱来", "威胁", "拖延"]
    delta = 0
    if any(token in clean for token in positive_tokens):
        delta += 4
    if any(token in clean for token in negative_tokens):
        delta -= 4
    if encounter.type == "npc" and any(token in clean for token in ["安抚", "谈", "说", "解释"]):
        delta += 2
    return _clamp(delta, -8, 8)


def _sanitize_outcome_package(encounter: EncounterEntry, package: EncounterOutcomePackage) -> EncounterOutcomePackage:
    result = package.result if package.result in {"success", "failure"} else _situation_result(encounter)
    rep_delta = int(package.reputation_delta or 0)
    if result == "success":
        rep_delta = _clamp(rep_delta if rep_delta > 0 else 6, 4, 12)
    else:
        rep_delta = -_clamp(abs(rep_delta if rep_delta < 0 else -6), 4, 12)
    items: list[InventoryItem] = []
    for index, item in enumerate(package.item_rewards[:2], start=1):
        items.append(
            item.model_copy(
                update={
                    "item_id": item.item_id or f"{encounter.encounter_id}_reward_{index}",
                    "item_type": "misc",
                    "slot_type": "misc",
                    "quantity": max(1, int(item.quantity or 1)),
                }
            )
        )
    return EncounterOutcomePackage(
        result=result,  # type: ignore[arg-type]
        reputation_delta=rep_delta,
        npc_relation_deltas=[
            EncounterOutcomeChange(
                target_id=item.target_id,
                delta=_clamp(item.delta, -4, 4),
                summary=(item.summary or "")[:120],
            )
            for item in package.npc_relation_deltas[:4]
            if (item.target_id or "").strip()
        ],
        team_deltas=[
            EncounterOutcomeChange(
                target_id=item.target_id,
                delta=_clamp(item.delta, -4, 4),
                summary=(item.summary or "")[:120],
            )
            for item in package.team_deltas[:4]
            if (item.target_id or "").strip()
        ],
        item_rewards=items,
        buff_rewards=[item.model_copy() for item in package.buff_rewards[:2]],
        resource_deltas=[str(item)[:120] for item in package.resource_deltas[:4]],
        narrative_summary=(package.narrative_summary or encounter.latest_outcome_summary or encounter.scene_summary or encounter.description)[:240],
    )


def _fallback_outcome_package(save, encounter: EncounterEntry) -> EncounterOutcomePackage:
    result = _situation_result(encounter)
    relation_delta = 2 if result == "success" else -2
    team_delta = 1 if result == "success" else -1
    rep_abs = _clamp(abs(encounter.situation_value - 50) // 5 + 4, 4, 12)
    item_rewards: list[InventoryItem] = []
    if result == "success" and encounter.situation_value >= 75:
        item_rewards.append(
            InventoryItem(
                item_id=f"{encounter.encounter_id}_token",
                name=f"{encounter.title}的纪念物",
                item_type="misc",
                slot_type="misc",
                description="一件在遭遇善后后留下的杂项物件。",
                quantity=1,
                value=max(1, encounter.situation_value // 10),
            )
        )
    return EncounterOutcomePackage(
        result=result,  # type: ignore[arg-type]
        reputation_delta=(rep_abs if result == "success" else -rep_abs),
        npc_relation_deltas=(
            [EncounterOutcomeChange(target_id=encounter.npc_role_id, delta=relation_delta, summary="遭遇结果影响了关键 NPC 对玩家的判断。")]
            if encounter.npc_role_id
            else []
        ),
        team_deltas=[
            EncounterOutcomeChange(
                target_id=member.role_id,
                delta=team_delta,
                summary=("共同处理遭遇提升了默契。" if result == "success" else "遭遇失利让队伍一时紧张。"),
            )
            for member in getattr(save.team_state, "members", [])[:3]
        ],
        item_rewards=item_rewards,
        buff_rewards=[],
        resource_deltas=[],
        narrative_summary=(encounter.latest_outcome_summary or encounter.scene_summary or encounter.description)[:240],
    )


def _apply_outcome_package(save, session_id: str, encounter: EncounterEntry, package: EncounterOutcomePackage) -> list[str]:
    applied_summaries: list[str] = []
    if package.reputation_delta:
        entry, _ = apply_sub_zone_reputation_delta(
            save,
            session_id=session_id,
            delta=_clamp(package.reputation_delta, -12, 12),
            reason=f"遭遇《{encounter.title}》结算",
            append_scene_event=False,
            append_log=True,
        )
        if entry is not None:
            applied_summaries.append(f"区域声望 {package.reputation_delta:+d} -> {entry.score}/100")
    for change in package.npc_relation_deltas:
        role = next((item for item in save.role_pool if item.role_id == change.target_id), None)
        if role is None:
            continue
        relation = next((item for item in role.relations if item.target_role_id == save.player_static_data.player_id), None)
        current_tag = relation.relation_tag if relation is not None else "neutral"
        ladder = ["hostile", "wary", "neutral", "met", "friendly", "ally"]
        try:
            idx = ladder.index(current_tag)
        except ValueError:
            idx = ladder.index("neutral")
        next_idx = _clamp(idx + (1 if change.delta > 0 else -1), 0, len(ladder) - 1) if change.delta != 0 else idx
        if relation is None:
            from app.models.schemas import RoleRelation

            role.relations.append(RoleRelation(target_role_id=save.player_static_data.player_id, relation_tag=ladder[next_idx], note="遭遇结算"))
        else:
            relation.relation_tag = ladder[next_idx]
            relation.note = "遭遇结算"
        applied_summaries.append(f"{role.name} 关系 {change.delta:+d}")
    for change in package.team_deltas:
        member = next((item for item in getattr(save.team_state, "members", []) if item.role_id == change.target_id), None)
        if member is None:
            continue
        member.affinity = _clamp(member.affinity + change.delta * 3, 0, 100)
        member.trust = _clamp(member.trust + change.delta * 2, 0, 100)
        applied_summaries.append(f"{member.name} 默契 {change.delta:+d}")
    for item in package.item_rewards:
        save.player_static_data.dnd5e_sheet.backpack.items.append(item.model_copy())
        applied_summaries.append(f"获得物品：{item.name}")
    for buff in package.buff_rewards:
        if not any(item.buff_id == buff.buff_id for item in save.player_static_data.dnd5e_sheet.buffs):
            save.player_static_data.dnd5e_sheet.buffs.append(buff.model_copy())
            applied_summaries.append(f"获得效果：{buff.name}")
    for resource in package.resource_deltas:
        applied_summaries.append(resource)
    encounter.last_outcome_package = package
    _append_game_log(
        save,
        session_id,
        "encounter_outcome_package",
        package.narrative_summary or f"遭遇《{encounter.title}》完成结算。",
        {
            "encounter_id": encounter.encounter_id,
            "result": package.result,
            "reputation_delta": package.reputation_delta,
        },
    )
    return applied_summaries


def _finalize_encounter_if_needed(save, state: EncounterState, encounter: EncounterEntry, *, session_id: str) -> tuple[EncounterOutcomePackage | None, list[str]]:
    if not _encounter_should_resolve(encounter):
        return None, []
    encounter.status = "resolved"
    encounter.resolved_at = _utc_now()
    if encounter.encounter_id in state.pending_ids:
        state.pending_ids = [item for item in state.pending_ids if item != encounter.encounter_id]
    if state.active_encounter_id == encounter.encounter_id:
        state.active_encounter_id = None
    package = _sanitize_outcome_package(encounter, _fallback_outcome_package(save, encounter))
    applied = _apply_outcome_package(save, session_id, encounter, package)
    resolution_text = package.narrative_summary or encounter.latest_outcome_summary or encounter.scene_summary or encounter.description
    _append_step(encounter, kind="resolution", content=resolution_text)
    return package, applied


def _append_step(
    encounter: EncounterEntry,
    *,
    kind: str,
    content: str,
    actor_type: str = "system",
    actor_id: str = "",
    actor_name: str = "",
) -> EncounterStepEntry:
    step = EncounterStepEntry(
        step_id=_new_id("estep"),
        kind=kind,  # type: ignore[arg-type]
        actor_type=actor_type,  # type: ignore[arg-type]
        actor_id=actor_id,
        actor_name=actor_name,
        content=content,
    )
    encounter.steps.append(step)
    encounter.steps = encounter.steps[-40:]
    encounter.last_advanced_at = step.created_at
    encounter.latest_outcome_summary = content[:240]
    return step


def _default_termination_conditions(encounter_type: str) -> list[EncounterTerminationCondition]:
    conditions = [
        EncounterTerminationCondition(
            condition_id=_new_id("eterm"),
            kind="player_escapes",
            description="玩家成功脱离当前遭遇并离开现场。",
        ),
        EncounterTerminationCondition(
            condition_id=_new_id("eterm"),
            kind="time_elapsed",
            description="局势在时间推进后自然结束。",
        ),
    ]
    if encounter_type == "npc":
        conditions.insert(
            0,
            EncounterTerminationCondition(
                condition_id=_new_id("eterm"),
                kind="npc_leaves",
                description="关键 NPC 主动离开或中断这次互动。",
            ),
        )
    else:
        conditions.insert(
            0,
            EncounterTerminationCondition(
                condition_id=_new_id("eterm"),
                kind="target_resolved",
                description="遭遇核心目标被处理、确认或排除。",
            ),
        )
    return conditions


def _termination_conditions_text(encounter: EncounterEntry) -> str:
    if not encounter.termination_conditions:
        return "none"
    lines = []
    for idx, item in enumerate(encounter.termination_conditions):
        marker = "done" if item.satisfied else "pending"
        lines.append(f"{idx}:{item.kind}:{marker}:{item.description}")
    return "\n".join(lines)


def _recent_steps_text(encounter: EncounterEntry, count: int = 6) -> str:
    if not encounter.steps:
        return "none"
    return "\n".join(f"[{item.kind}] {item.actor_name or item.actor_type}: {item.content}" for item in encounter.steps[-count:])


def _apply_termination_updates(encounter: EncounterEntry, updates: object) -> bool:
    changed = False
    if not isinstance(updates, list):
        return False
    for raw in updates:
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("condition_index"))
        except Exception:
            continue
        if index < 0 or index >= len(encounter.termination_conditions):
            continue
        condition = encounter.termination_conditions[index]
        next_value = bool(raw.get("satisfied"))
        if next_value and not condition.satisfied:
            condition.satisfied = True
            condition.satisfied_at = _utc_now()
            changed = True
    return changed


def _encounter_should_resolve(encounter: EncounterEntry) -> bool:
    if encounter.situation_value <= 0 or encounter.situation_value >= 100:
        return True
    return any(item.satisfied for item in encounter.termination_conditions)


def _current_area_text(save) -> str:
    zone_id = save.area_snapshot.current_zone_id
    sub_zone_id = save.area_snapshot.current_sub_zone_id
    zone_name = next((item.name for item in save.area_snapshot.zones if item.zone_id == zone_id), zone_id or "当前区域")
    sub_name = next((item.name for item in save.area_snapshot.sub_zones if item.sub_zone_id == sub_zone_id), sub_zone_id or "附近")
    return f"{zone_name} / {sub_name}"


def _extract_json_content(content: str) -> dict[str, Any]:
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    return json.loads(raw)


def _prompt_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _force_chinese_text(value: Any, fallback: str, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if not text or not _contains_cjk(text):
        text = fallback
    text = " ".join(str(text or fallback).split())
    return text[:limit]


def _sanitize_allowed_id(value: Any, allowed_ids: set[str]) -> str:
    candidate = str(value or "").strip()
    if not candidate or candidate not in allowed_ids:
        return ""
    return candidate


def _current_area_data(save) -> tuple[str, str, str | None, str | None]:
    zone_id = save.area_snapshot.current_zone_id
    sub_zone_id = save.area_snapshot.current_sub_zone_id
    zone_name = next((item.name for item in save.area_snapshot.zones if item.zone_id == zone_id), "当前区域")
    sub_name = next((item.name for item in save.area_snapshot.sub_zones if item.sub_zone_id == sub_zone_id), "附近")
    return zone_name, sub_name, zone_id, sub_zone_id


def _has_pending_quest(save) -> bool:
    return any(item.status == "pending_offer" for item in save.quest_state.quests)


def _active_quests(save):
    return [item for item in save.quest_state.quests if item.status == "active"]


def _current_fate_phase(save):
    fate = save.fate_state.current_fate
    if fate is None:
        return None
    return next((phase for phase in fate.phases if phase.phase_id == fate.current_phase_id), None)


def _random_should_trigger(trigger_kind: str, force_enabled: bool) -> bool:
    if force_enabled:
        return True
    if trigger_kind in {"quest_rule", "fate_rule", "scripted", "debug_forced"}:
        return True
    chance = 0.35 if trigger_kind == "random_move" else 0.22
    return random.random() < chance


def _has_active_resolve_objective(save) -> bool:
    for quest in _active_quests(save):
        if any(obj.kind == "resolve_encounter" for obj in quest.objectives):
            return True
    return False


def _fallback_encounter(save, trigger_kind: str) -> EncounterEntry:
    zone_name, sub_name, zone_id, sub_zone_id = _current_area_data(save)
    active_quests = _active_quests(save)
    phase = _current_fate_phase(save)
    global_pref = prompt_table.get_text(
        "encounter.global.preference",
        "默认遭遇：抢劫、可疑NPC、异常痕迹、遗落宝箱。偏好偏向奇幻冒险和轻度悬疑。",
    )

    if active_quests:
        quest = active_quests[0]
        if any(obj.kind == "resolve_encounter" for obj in quest.objectives):
            return EncounterEntry(
                encounter_id=_new_id("enc"),
                type=("anomaly" if quest.source == "fate" else "event"),
                trigger_kind=("fate_rule" if quest.source == "fate" else "quest_rule"),
                encounter_mode="standard",
                title=f"与【{quest.title}】相关的异动",
                description=f"你在【{zone_name}/{sub_name}】察觉到一场与任务【{quest.title}】有关的异动。{global_pref[:36]}",
                zone_id=zone_id,
                sub_zone_id=sub_zone_id,
                related_quest_ids=[quest.quest_id],
                related_fate_phase_ids=([quest.fate_phase_id] if quest.fate_phase_id else []),
                generated_prompt_tags=["quest", "progress", zone_name],
                scene_summary=f"{zone_name}/{sub_name} 中出现了与任务推进有关的突然动静。",
                termination_conditions=_default_termination_conditions("event"),
            )

    if phase is not None and trigger_kind == "fate_rule" and _has_active_resolve_objective(save):
        return EncounterEntry(
            encounter_id=_new_id("enc"),
            type="anomaly",
            trigger_kind="fate_rule",
            encounter_mode="standard",
            title=f"命运相位：{phase.title}",
            description=f"【{zone_name}/{sub_name}】出现与你的命运阶段【{phase.title}】有关的异常迹象。{global_pref[:36]}",
            zone_id=zone_id,
            sub_zone_id=sub_zone_id,
            related_fate_phase_ids=[phase.phase_id],
            generated_prompt_tags=["fate", "anomaly", zone_name],
            scene_summary=f"{zone_name}/{sub_name} 里忽然出现了不自然的命运征兆。",
            termination_conditions=_default_termination_conditions("anomaly"),
        )

    base_templates = [
        ("event", f"{zone_name}里的可疑痕迹", f"你在【{zone_name}/{sub_name}】发现一串刚留下不久的可疑痕迹。"),
        ("npc", f"{sub_name}的陌生人", f"一名看起来并不属于【{sub_name}】的人正悄悄观察四周。"),
        ("anomaly", f"{sub_name}的异常回响", f"空气里掠过一阵不自然的波动，像有什么在【{sub_name}】被短暂唤醒。"),
    ]
    idx = 0 if trigger_kind == "random_move" else 1
    typ, title, description = base_templates[idx if idx < len(base_templates) else 0]
    return EncounterEntry(
        encounter_id=_new_id("enc"),
        type=typ,  # type: ignore[arg-type]
        trigger_kind=trigger_kind if trigger_kind in {"random_move", "random_dialog", "scripted", "quest_rule", "fate_rule", "debug_forced"} else "random_move",  # type: ignore[arg-type]
        encounter_mode=("npc_initiated_chat" if typ == "npc" and trigger_kind == "random_dialog" else "standard"),
        title=title,
        description=f"{description}{global_pref[:28]}",
        zone_id=zone_id,
        sub_zone_id=sub_zone_id,
        generated_prompt_tags=[zone_name, sub_name, typ],
        scene_summary=f"{zone_name}/{sub_name} 里突发了一件需要立刻回应的事。",
        termination_conditions=_default_termination_conditions(typ),
    )


def _ai_generate_encounter(save, trigger_kind: str, config: ChatConfig | None) -> EncounterEntry | None:
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    zone_name, sub_name, zone_id, sub_zone_id = _current_area_data(save)
    quest_titles = " / ".join(item.title for item in _active_quests(save)) or "无活动任务"
    phase = _current_fate_phase(save)
    phase_title = phase.title if phase is not None else "无命运阶段"
    default_prompt = (
        "你是跑团遭遇设计器，只输出 JSON。"
        "结构：{\"type\":\"npc|event|anomaly\",\"title\":\"\",\"description\":\"\",\"tags\":[\"\"]}。"
        "全局遭遇偏好=$global_pref。区域=$zone_name/$sub_name。触发原因=$trigger_kind。活动任务=$quest_titles。当前命运阶段=$phase_title。"
    )
    prompt = prompt_table.render(
        PromptKeys.ENCOUNTER_GENERATE_USER,
        default_prompt,
        global_pref=prompt_table.get_text("encounter.global.preference", "奇幻冒险、随机异象、可疑NPC、宝箱与伏击。"),
        zone_name=zone_name,
        sub_name=sub_name,
        trigger_kind=trigger_kind,
        quest_titles=quest_titles,
        phase_title=phase_title,
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("encounter.generate.system", "你只输出 JSON。")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
        typ = str(parsed.get("type") or "event").strip().lower()
        if typ not in {"npc", "event", "anomaly"}:
            typ = "event"
        title = str(parsed.get("title") or "").strip()
        description = str(parsed.get("description") or "").strip()
        tags = parsed.get("tags") if isinstance(parsed.get("tags"), list) else []
        clean_tags = [str(item).strip() for item in tags[:6] if str(item).strip()]
        if not title or not description:
            return None
        active_quests = _active_quests(save)
        return EncounterEntry(
            encounter_id=_new_id("enc"),
            type=typ,  # type: ignore[arg-type]
            trigger_kind=trigger_kind if trigger_kind in {"random_move", "random_dialog", "scripted", "quest_rule", "fate_rule", "debug_forced"} else "random_move",  # type: ignore[arg-type]
            title=title,
            description=description,
            zone_id=zone_id,
            sub_zone_id=sub_zone_id,
            related_quest_ids=[item.quest_id for item in active_quests[:2]],
            related_fate_phase_ids=([phase.phase_id] if phase is not None else []),
            generated_prompt_tags=clean_tags,
        )
    except Exception:
        return None


def _ai_generate_encounter_guarded(save, trigger_kind: str, config: ChatConfig | None) -> EncounterEntry | None:
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None

    zone_name, sub_name, zone_id, sub_zone_id = _current_area_data(save)
    snapshot = build_global_story_snapshot(save)
    entity_index = build_entity_index(save, scope="current_zone")
    allowed_npc_ids = set(snapshot.available_npc_ids)
    allowed_zone_ids = set(entity_index.zone_ids)
    allowed_sub_zone_ids = set(entity_index.sub_zone_ids)
    allowed_quest_ids = set(snapshot.active_quest_ids)
    allowed_fate_phase_ids = set(entity_index.fate_phase_ids)
    active_quests = _active_quests(save)
    phase = _current_fate_phase(save)
    fallback_encounter = _fallback_encounter(save, trigger_kind)
    default_prompt = (
        "你要设计一个持续型跑团遭遇，且只能返回 JSON。\n"
        "所有可见文本字段都必须使用简体中文，不允许输出英文标题、英文描述或英文叙事。\n"
        "Schema: {\"type\":\"npc|event|anomaly\",\"title\":\"\",\"description\":\"\",\"npc_role_id\":\"optional\",\"temporary_npcs\":[{\"name\":\"\",\"title\":\"\",\"description\":\"\",\"speaking_style\":\"\",\"agenda\":\"\"}],\"scene_summary\":\"\",\"termination_conditions\":[{\"kind\":\"npc_leaves|player_escapes|target_resolved|time_elapsed|manual_custom\",\"description\":\"\"}],\"tags\":[\"\"]}。\n"
        "若 type=npc，则 npc_role_id 必填，且只能从允许列表中选择。\n"
        "temporary_npcs 用于遭遇现场临时出现的 NPC，只在这次遭遇中存在，最多 2 名。\n"
        "禁止编造 npc id、zone id、sub-zone id、quest id 或 fate phase id。\n"
        "遭遇需要有立刻发生的现场感，title、description、scene_summary 和 termination_conditions.description 都必须是简体中文。"
    )
    prompt = prompt_table.render(
        PromptKeys.ENCOUNTER_GENERATE_USER,
        default_prompt,
        global_pref=prompt_table.get_text("encounter.global.preference", "奇幻遭遇"),
        zone_name=zone_name,
        sub_name=sub_name,
        trigger_kind=trigger_kind,
        current_fate_id=snapshot.current_fate_id or "none",
        current_fate_phase_id=snapshot.current_fate_phase_id or "none",
        allowed_npc_ids=_prompt_list(sorted(allowed_npc_ids)),
        allowed_zone_ids=_prompt_list(sorted(allowed_zone_ids)),
        allowed_sub_zone_ids=_prompt_list(sorted(allowed_sub_zone_ids)),
        allowed_quest_ids=_prompt_list(sorted(allowed_quest_ids)),
        allowed_fate_phase_ids=_prompt_list(sorted(allowed_fate_phase_ids)),
        visible_npcs=_prompt_list([f"{npc.role_id}:{npc.name}" for npc in snapshot.available_npcs]),
        active_quests=_prompt_list([f"{quest.quest_id}:{quest.title}" for quest in snapshot.active_quests]),
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("encounter.generate.system", "你只输出 JSON。所有文本字段使用简体中文。")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
        typ = str(parsed.get("type") or "event").strip().lower()
        if typ not in {"npc", "event", "anomaly"}:
            typ = "event"
        title = _force_chinese_text(parsed.get("title"), fallback_encounter.title, limit=80)
        description = _force_chinese_text(parsed.get("description"), fallback_encounter.description, limit=240)
        scene_summary = _force_chinese_text(
            parsed.get("scene_summary"),
            fallback_encounter.scene_summary or fallback_encounter.description,
            limit=240,
        )
        tags = parsed.get("tags") if isinstance(parsed.get("tags"), list) else []
        clean_tags = [str(item).strip()[:40] for item in tags[:6] if str(item).strip()]
        if not title or not description:
            return None

        entity_refs: list[EntityRef] = []
        npc_role_id = _sanitize_allowed_id(parsed.get("npc_role_id"), allowed_npc_ids)
        temporary_npcs = _sanitize_temporary_npcs(parsed.get("temporary_npcs"))
        termination_conditions_raw = parsed.get("termination_conditions") if isinstance(parsed.get("termination_conditions"), list) else []
        termination_conditions: list[EncounterTerminationCondition] = []
        for raw in termination_conditions_raw[:5]:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind") or "").strip()
            description_text = _force_chinese_text(raw.get("description"), "", limit=160)
            if kind not in {"npc_leaves", "player_escapes", "target_resolved", "time_elapsed", "manual_custom"}:
                continue
            if not description_text:
                continue
            termination_conditions.append(
                EncounterTerminationCondition(
                    condition_id=_new_id("eterm"),
                    kind=kind,  # type: ignore[arg-type]
                    description=description_text,
                )
            )
        if typ == "npc":
            if not npc_role_id:
                return None
            npc_name = next((item.name for item in save.role_pool if item.role_id == npc_role_id), npc_role_id)
            if npc_name not in title:
                title = f"{npc_name}: {title}"
            entity_refs.append(EntityRef(entity_type="npc", entity_id=npc_role_id, label=npc_name))

        encounter = EncounterEntry(
            encounter_id=_new_id("enc"),
            type=typ,  # type: ignore[arg-type]
            trigger_kind=trigger_kind if trigger_kind in {"random_move", "random_dialog", "scripted", "quest_rule", "fate_rule", "debug_forced"} else "random_move",  # type: ignore[arg-type]
            encounter_mode=("npc_initiated_chat" if typ == "npc" and trigger_kind == "random_dialog" else "standard"),
            title=title,
            description=description,
            zone_id=zone_id,
            sub_zone_id=sub_zone_id,
            npc_role_id=npc_role_id or None,
            temporary_npcs=temporary_npcs,
            related_quest_ids=[item.quest_id for item in active_quests[:2]],
            related_fate_phase_ids=([phase.phase_id] if phase is not None else []),
            generated_prompt_tags=clean_tags,
            scene_summary=scene_summary,
            termination_conditions=termination_conditions or _default_termination_conditions(typ),
        )
        encounter.entity_refs = extract_entity_refs_from_encounter(encounter) + entity_refs
        return encounter
    except Exception:
        return None


def get_pending_encounters(session_id: str) -> EncounterPendingResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    state = _state(save)
    pending = _pending_entries(state)
    active = _current_active_encounter(state)
    return EncounterPendingResponse(session_id=session_id, encounter_state=state, pending=pending, active_encounter=active)


def get_encounter_history(session_id: str) -> EncounterHistoryResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    state = _state(save)
    return EncounterHistoryResponse(session_id=session_id, items=state.history)


def set_debug_force_toggle(req: EncounterForceToggleRequest) -> EncounterForceToggleResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    enabled = (not state.debug_force_trigger) if req.enabled is None else bool(req.enabled)
    state.debug_force_trigger = enabled
    _touch_state(state)
    save_current(save)
    return EncounterForceToggleResponse(session_id=req.session_id, enabled=enabled, encounter_state=state)


def check_for_encounter(req: EncounterCheckRequest) -> EncounterCheckResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    world_state = ensure_world_state(save)
    if _current_active_encounter(state) is not None:
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))

    if req.trigger_kind in {"random_move", "random_dialog"} and _pending_entries(state):
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))

    if len(state.pending_ids) >= 5:
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))

    if req.trigger_kind in {"quest_rule", "fate_rule"} and not _has_active_resolve_objective(save):
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))

    should_trigger = _random_should_trigger(req.trigger_kind, state.debug_force_trigger)
    if not should_trigger:
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))

    encounter = _ai_generate_encounter_guarded(save, req.trigger_kind, req.config) or _fallback_encounter(save, req.trigger_kind)
    encounter.source_world_revision = world_state.world_revision
    encounter.source_map_revision = world_state.map_revision
    encounter.situation_start_value = _calculate_initial_situation_value(save, encounter)
    encounter.situation_value = encounter.situation_start_value
    encounter.situation_trend = "stable"
    _refresh_participants(save, encounter)
    base_refs = extract_entity_refs_from_encounter(encounter)
    unique_refs: dict[tuple[str, str], EntityRef] = {}
    for ref in [*base_refs, *(encounter.entity_refs or [])]:
        unique_refs[(ref.entity_type, ref.entity_id)] = ref
    encounter.entity_refs = list(unique_refs.values())
    if validate_entity_refs(save, encounter.entity_refs):
        encounter.status = "invalidated"
        encounter.invalidated_reason = "missing_entity_ref"
        state.encounters.append(encounter)
        _touch_state(state)
        save_current(save)
        return EncounterCheckResponse(ok=True, generated=False, blocked_by_higher_priority_modal=_has_pending_quest(save))
    state.encounters.append(encounter)
    state.pending_ids.append(encounter.encounter_id)
    _touch_state(state)
    _append_game_log(
        save,
        req.session_id,
        "encounter_generated",
        f"遭遇已生成【{encounter.title}】",
        {
            "encounter_id": encounter.encounter_id,
            "encounter_type": encounter.type,
            "title": encounter.title,
            "description": encounter.description,
        },
    )
    save_current(save)
    return EncounterCheckResponse(
        ok=True,
        generated=True,
        encounter_id=encounter.encounter_id,
        blocked_by_higher_priority_modal=_has_pending_quest(save),
        encounter=encounter,
    )


def present_encounter(encounter_id: str, req: EncounterPresentRequest) -> EncounterPresentResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    encounter = _find_encounter(state, encounter_id)
    if encounter.invalidated_reason or encounter.status == "invalidated":
        raise ValueError("ENCOUNTER_INVALIDATED")
    if encounter.status not in {"queued", "active", "escaped"}:
        raise ValueError("ENCOUNTER_INVALID_STATUS")
    if encounter.status == "queued":
        encounter.status = "active"
        encounter.presented_at = _utc_now()
        encounter.player_presence = "engaged"
        encounter.last_advanced_at = encounter.presented_at
        _initialize_encounter_state(save, encounter)
        if not encounter.termination_conditions:
            encounter.termination_conditions = _default_termination_conditions(encounter.type)
        encounter.scene_summary = encounter.scene_summary or encounter.description
        encounter.latest_outcome_summary = f"就在这时，{encounter.description}"
        _append_step(encounter, kind="announcement", content=encounter.latest_outcome_summary)
        _append_game_log(
            save,
            req.session_id,
            "encounter_presented",
            f"遭遇开始：《{encounter.title}》",
            {
                "encounter_id": encounter.encounter_id,
                "encounter_type": encounter.type,
                "title": encounter.title,
                "description": encounter.description,
            },
        )
    state.active_encounter_id = encounter.encounter_id
    _touch_state(state)
    save_current(save)
    return EncounterPresentResponse(
        session_id=req.session_id,
        encounter_id=encounter.encounter_id,
        status=encounter.status,
        encounter=encounter,
    )


def _legacy_unused_resolve_fallback_reply_v0(encounter: EncounterEntry, player_prompt: str) -> tuple[str, int]:
    minutes = max(1, min(15, ceil(len(player_prompt.strip()) / 30)))
    if encounter.type == "npc":
        return (f"对方先打量了你一眼，然后低声回应了你的试探，显然不想在公开场合多说。", minutes)
    if encounter.type == "anomaly":
        return (f"你的动作引发了更明显的异样回响，周围环境短暂变得不自然，但你抓住了一条可继续追查的线索。", minutes)
    return (f"你的举动让这场遭遇有了明确进展，现场留下的细节足够你继续推进调查。", minutes)


def _legacy_unused_ai_resolve_encounter_v0(encounter: EncounterEntry, req: EncounterActRequest) -> dict[str, object] | None:
    config = req.config
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    fallback_reply, fallback_minutes = _resolve_fallback_reply(encounter, req.player_prompt)
    default_prompt = (
        "\u4f60\u8981\u63a8\u8fdb\u4e00\u4e2a\u8dd1\u56e2\u906d\u9047\u6b65\u9aa4\uff0c\u53ea\u80fd\u8fd4\u56de JSON\u3002\n"
        "reply \u548c scene_summary \u5fc5\u987b\u4f7f\u7528\u7b80\u4f53\u4e2d\u6587\uff0c\u4e0d\u5141\u8bb8\u8f93\u51fa\u82f1\u6587\u53d9\u4e8b\u3002\n"
        "\u4f60\u53ea\u80fd\u63cf\u5199\u73af\u5883\u3001\u4e8b\u7269\u3001\u5c40\u52bf\u3001\u76ee\u6807\u53cd\u9988\u548c\u7cfb\u7edf\u6027\u53d8\u5316\uff0c\u4e0d\u5141\u8bb8\u4ee3\u66ff\u73b0\u573a NPC \u6216\u961f\u53cb\u53d1\u8a00\u3002\n"
        "\u82e5\u73a9\u5bb6\u672c\u8f6e\u9009\u62e9\u65c1\u89c2\u4e0e\u7b49\u5f85\uff0c\u5c31\u628a\u8fd9\u4e00\u8f6e\u89c6\u4e3a\u5c40\u52bf\u81ea\u884c\u63a8\u8fdb\uff0c\u4e0d\u8981\u7f16\u9020\u73a9\u5bb6\u4e3b\u52a8\u52a8\u4f5c\u3002\n"
        "JSON schema: "
        "{\"reply\":\"...\",\"time_spent_min\":1,\"scene_summary\":\"...\","
        "\"situation_delta_hint\":0,"
        "\"step_kind\":\"gm_update|resolution\","
        "\"termination_updates\":[{\"condition_index\":0,\"satisfied\":true}]}"
    )
    prompt = prompt_table.render(
        PromptKeys.ENCOUNTER_STEP_USER,
        default_prompt,
        title=encounter.title,
        description=encounter.description,
        encounter_mode=encounter.encounter_mode,
        player_presence=encounter.player_presence,
        scene_summary=encounter.scene_summary or encounter.description,
        termination_conditions=_termination_conditions_text(encounter),
        recent_steps=_recent_steps_text(encounter),
        player_prompt=req.player_prompt,
        team_members="none",
        visible_npcs="none",
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("encounter.resolve.system", "\u4f60\u53ea\u8f93\u51fa JSON\u3002\u6240\u6709\u6587\u672c\u5b57\u6bb5\u4f7f\u7528\u7b80\u4f53\u4e2d\u6587\u3002")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
        reply = _force_chinese_text(parsed.get("reply"), fallback_reply, limit=240)
        minutes = max(1, min(30, int(parsed.get("time_spent_min") or fallback_minutes or 1)))
        if not reply:
            return None
        step_kind = str(parsed.get("step_kind") or "gm_update").strip().lower()
        if step_kind not in {"gm_update", "resolution"}:
            step_kind = "gm_update"
        scene_summary = _force_chinese_text(parsed.get("scene_summary"), encounter.scene_summary or encounter.description, limit=240)
        termination_updates = parsed.get("termination_updates")
        if not isinstance(termination_updates, list):
            termination_updates = []
        return {
            "reply": reply,
            "time_spent_min": minutes,
            "scene_summary": scene_summary,
            "situation_delta_hint": _clamp(int(parsed.get("situation_delta_hint") or 0), -8, 8),
            "step_kind": step_kind,
            "termination_updates": termination_updates,
        }
    except Exception:
        return None


def _legacy_unused_fallback_step_updates_v0(encounter: EncounterEntry, player_prompt: str) -> tuple[str, list[dict[str, object]], str]:
    clean = (player_prompt or "").strip()
    updates: list[dict[str, object]] = []
    step_kind = "gm_update"
    scene_summary = encounter.scene_summary or encounter.description
    if any(token in clean for token in ["搞清", "确认", "解决", "谈妥", "处理完", "拿到"]):
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "target_resolved":
                updates.append({"condition_index": index, "satisfied": True})
                break
    if encounter.type == "npc" and any(token in clean for token in ["散了", "走开", "不聊", "闭嘴"]):
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "npc_leaves":
                updates.append({"condition_index": index, "satisfied": True})
                break
    return scene_summary, updates, step_kind


def _encounter_specific_defaults(encounter: EncounterEntry, player_prompt: str) -> tuple[str, str, str, str]:
    clean_prompt = " ".join((player_prompt or "").split()).strip() or "本轮行动"
    focus_title = encounter.title or "当前遭遇"
    scene_summary = " ".join((encounter.scene_summary or encounter.description or focus_title).split()).strip()
    first_temp = next((item for item in getattr(encounter, "temporary_npcs", []) or [] if item.name), None)
    focus_actor = first_temp.name if first_temp is not None else ("现场 NPC" if encounter.npc_role_id else "现场")
    termination_text = next((item.description for item in encounter.termination_conditions if item.description), "")
    specific_change = f"你刚做出“{clean_prompt[:36]}”后，{focus_actor}立刻围绕“{focus_title}”采取了动作，现场变化变得明确：{scene_summary}"
    specific_threat = termination_text or f"{focus_title}里最直接的阻碍仍然是：{scene_summary}"
    opened_opportunity = f"你下一轮可以直接介入“{focus_title}”，优先处理“{specific_threat[:48]}”"
    return scene_summary, specific_change[:180], specific_threat[:180], opened_opportunity[:180]


def _legacy_unused_concretize_encounter_reply_v1(
    encounter: EncounterEntry,
    player_prompt: str,
    *,
    reply: str,
    scene_summary: str,
    specific_change: str = "",
    specific_threat: str = "",
    opened_opportunity: str = "",
) -> tuple[str, str]:
    fallback_scene, fallback_change, fallback_threat, fallback_opportunity = _encounter_specific_defaults(encounter, player_prompt)
    change_text = _force_chinese_text(specific_change, fallback_change, limit=180)
    threat_text = _force_chinese_text(specific_threat, fallback_threat, limit=180)
    opportunity_text = _force_chinese_text(opened_opportunity, fallback_opportunity, limit=180)
    summary_text = _force_chinese_text(scene_summary, fallback_scene, limit=240)
    if _text_is_too_vague(summary_text):
        summary_text = f"{change_text} 当前最直接的风险是：{threat_text}。"
    reply_text = _force_chinese_text(reply, "", limit=240)
    if _text_is_too_vague(reply_text):
        reply_text = f"{change_text} 当前最直接的风险是：{threat_text}。这给你留下的明确机会是：{opportunity_text}。"
    return reply_text[:240], summary_text[:240]


def _legacy_unused_resolve_fallback_reply_v1(encounter: EncounterEntry, player_prompt: str) -> tuple[str, int]:
    minutes = max(1, min(15, ceil(len(player_prompt.strip()) / 30)))
    reply, _ = _concretize_encounter_reply(
        encounter,
        player_prompt,
        reply="",
        scene_summary=encounter.scene_summary or encounter.description or encounter.title,
    )
    return reply, minutes


def _legacy_unused_ai_resolve_encounter_v1(encounter: EncounterEntry, req: EncounterActRequest) -> dict[str, object] | None:
    config = req.config
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    fallback_reply, fallback_minutes = _resolve_fallback_reply(encounter, req.player_prompt)
    save = get_current_save(default_session_id=req.session_id)
    team_members, visible_npcs = _visible_participant_text(save, encounter)
    default_prompt = (
        "你要推进一个跑团遭遇步骤，只能返回 JSON。\n"
        "reply、scene_summary、specific_change、specific_threat、opened_opportunity 都必须使用简体中文。\n"
        "不能写模糊句。禁止只写“发现危险”“情况恶化”“似乎有异常”“有某种力量”这类没有来源、对象、位置和后果的描述。\n"
        "必须明确写出：谁对什么做了什么，现场哪一处发生了什么变化，直接危险或障碍是什么，给玩家留下了什么机会或压力。\n"
        "你只能描述环境、事物、局势、目标反馈和系统性变化，不允许代替现场 NPC 或队友发言。\n"
        "若玩家本轮选择旁观与等待，就把这一轮视为局势自行推进，不要编造玩家主动动作。\n"
        "JSON schema: "
        "{\"reply\":\"...\",\"time_spent_min\":1,\"scene_summary\":\"...\","
        "\"specific_change\":\"...\",\"specific_threat\":\"...\",\"opened_opportunity\":\"...\","
        "\"situation_delta_hint\":0,"
        "\"step_kind\":\"gm_update|resolution\","
        "\"termination_updates\":[{\"condition_index\":0,\"satisfied\":true}]}"
    )
    prompt = prompt_table.render(
        PromptKeys.ENCOUNTER_STEP_USER,
        default_prompt,
        title=encounter.title,
        description=encounter.description,
        encounter_mode=encounter.encounter_mode,
        player_presence=encounter.player_presence,
        scene_summary=encounter.scene_summary or encounter.description,
        termination_conditions=_termination_conditions_text(encounter),
        recent_steps=_recent_steps_text(encounter),
        player_prompt=req.player_prompt,
        team_members=team_members,
        visible_npcs=visible_npcs,
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_table.get_text("encounter.resolve.system", "你只输出 JSON。所有文本字段使用简体中文。")},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
        minutes = max(1, min(30, int(parsed.get("time_spent_min") or fallback_minutes or 1)))
        step_kind = str(parsed.get("step_kind") or "gm_update").strip().lower()
        if step_kind not in {"gm_update", "resolution"}:
            step_kind = "gm_update"
        reply, scene_summary = _concretize_encounter_reply(
            encounter,
            req.player_prompt,
            reply=str(parsed.get("reply") or fallback_reply),
            scene_summary=str(parsed.get("scene_summary") or encounter.scene_summary or encounter.description),
            specific_change=str(parsed.get("specific_change") or ""),
            specific_threat=str(parsed.get("specific_threat") or ""),
            opened_opportunity=str(parsed.get("opened_opportunity") or ""),
        )
        if not reply:
            return None
        termination_updates = parsed.get("termination_updates")
        if not isinstance(termination_updates, list):
            termination_updates = []
        return {
            "reply": reply,
            "time_spent_min": minutes,
            "scene_summary": scene_summary,
            "specific_change": _force_chinese_text(parsed.get("specific_change"), "", limit=180),
            "specific_threat": _force_chinese_text(parsed.get("specific_threat"), "", limit=180),
            "opened_opportunity": _force_chinese_text(parsed.get("opened_opportunity"), "", limit=180),
            "situation_delta_hint": _clamp(int(parsed.get("situation_delta_hint") or 0), -8, 8),
            "step_kind": step_kind,
            "termination_updates": termination_updates,
        }
    except Exception:
        return None


def _legacy_unused_fallback_step_updates_v1(encounter: EncounterEntry, player_prompt: str) -> tuple[str, list[dict[str, object]], str]:
    clean = (player_prompt or "").strip()
    updates: list[dict[str, object]] = []
    scene_summary, _, _, _ = _encounter_specific_defaults(encounter, player_prompt)
    step_kind = "gm_update"
    if any(token in clean for token in ["搞清", "确认", "解决", "谈妥", "处理完", "拿到"]):
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "target_resolved":
                updates.append({"condition_index": index, "satisfied": True})
                break
    if encounter.type == "npc" and any(token in clean for token in ["散了", "离开", "不聊", "闭嘴"]):
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "npc_leaves":
                updates.append({"condition_index": index, "satisfied": True})
                break
    if updates:
        step_kind = "resolution"
    return scene_summary, updates, step_kind


def act_on_encounter(encounter_id: str, req: EncounterActRequest) -> EncounterActResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    encounter = _find_encounter(state, encounter_id)
    if encounter.invalidated_reason or encounter.status == "invalidated":
        raise ValueError("ENCOUNTER_INVALIDATED")
    if encounter.status not in {"queued", "active", "escaped"}:
        raise ValueError("ENCOUNTER_INVALID_STATUS")
    if encounter.status == "queued":
        encounter.status = "active"
        encounter.presented_at = _utc_now()
        encounter.player_presence = "engaged"
        _initialize_encounter_state(save, encounter)
    if encounter.status == "escaped":
        encounter.status = "active"
        encounter.player_presence = "engaged"
        state.active_encounter_id = encounter.encounter_id
    if encounter.presented_at is None:
        _initialize_encounter_state(save, encounter)

    _append_step(
        encounter,
        kind="player_action",
        actor_type="player",
        actor_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        content=req.player_prompt.strip(),
    )
    resolved = _ai_resolve_encounter(encounter, req)
    if resolved is None:
        reply, time_spent_min = _resolve_fallback_reply(encounter, req.player_prompt)
        next_scene_summary, termination_updates, step_kind = _fallback_step_updates(encounter, req.player_prompt)
        situation_delta_hint = _fallback_situation_delta(encounter, req.player_prompt)
    else:
        reply = str(resolved.get("reply") or "").strip()
        time_spent_min = max(1, min(30, int(resolved.get("time_spent_min") or 1)))
        next_scene_summary = str(resolved.get("scene_summary") or "").strip() or encounter.scene_summary or encounter.description
        termination_updates = resolved.get("termination_updates") if isinstance(resolved.get("termination_updates"), list) else []
        step_kind = str(resolved.get("step_kind") or "gm_update")
        situation_delta_hint = _clamp(int(resolved.get("situation_delta_hint") or 0), -8, 8)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()
    save.area_snapshot.clock = _advance_clock(save.area_snapshot.clock, time_spent_min)
    encounter.scene_summary = next_scene_summary
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    _append_step(encounter, kind=step_kind, content=reply)
    _apply_termination_updates(encounter, termination_updates)
    situation_delta = _clamp(situation_delta_hint + _check_bonus_from_player_prompt(req.player_prompt), -20, 20)
    if situation_delta != 0:
        encounter.situation_value = _clamp(encounter.situation_value + situation_delta, 0, 100)
        encounter.situation_trend = "improving" if situation_delta > 0 else "worsening"
    else:
        encounter.situation_trend = "stable"
    outcome_package, applied_outcome_summaries = _finalize_encounter_if_needed(
        save,
        state,
        encounter,
        session_id=req.session_id,
    )
    if outcome_package is None:
        encounter.status = "active"
        state.active_encounter_id = encounter.encounter_id

    resolution = EncounterResolution(
        encounter_id=encounter.encounter_id,
        player_prompt=req.player_prompt.strip(),
        reply=reply,
        time_spent_min=time_spent_min,
        quest_updates=[f"{quest_id}:progress" for quest_id in encounter.related_quest_ids],
        situation_delta=situation_delta,
        situation_value_after=encounter.situation_value,
        reputation_delta=(outcome_package.reputation_delta if outcome_package is not None else 0),
        applied_outcome_summaries=applied_outcome_summaries,
    )
    state.history.append(resolution)
    state.history = state.history[-80:]
    _touch_state(state)
    _append_game_log(
        save,
        req.session_id,
        ("encounter_resolved" if encounter.status == "resolved" else "encounter_progress"),
        (f"遭遇结束：《{encounter.title}》" if encounter.status == "resolved" else f"遭遇推进：《{encounter.title}》"),
        {
            "encounter_id": encounter.encounter_id,
            "encounter_type": encounter.type,
            "title": encounter.title,
            "description": encounter.description,
            "time_spent_min": time_spent_min,
        },
    )
    _append_game_log(
        save,
        req.session_id,
        "encounter_resolution_text",
        reply,
        {
            "encounter_id": encounter.encounter_id,
            "player_prompt": req.player_prompt,
        },
    )
    save_current(save)

    try:
        from app.models.schemas import QuestEvaluateAllRequest
        from app.services.quest_service import evaluate_all_quests

        evaluate_all_quests(QuestEvaluateAllRequest(session_id=req.session_id, config=req.config))
    except Exception:
        pass
    try:
        from app.models.schemas import FateEvaluateRequest
        from app.services.fate_service import evaluate_fate_state

        evaluate_fate_state(FateEvaluateRequest(session_id=req.session_id, config=req.config))
    except Exception:
        pass

    return EncounterActResponse(
        session_id=req.session_id,
        encounter_id=encounter.encounter_id,
        status=encounter.status,
        reply=reply,
        time_spent_min=time_spent_min,
        encounter=encounter,
        resolution=resolution,
        encounter_state=state,
    )


def _legacy_unused_advance_active_encounter_from_main_chat_in_save_v1(
    save,
    *,
    session_id: str,
    player_text: str,
    gm_narration: str,
    time_spent_min: int,
    config: ChatConfig | None = None,
) -> list:
    state = _state(save)
    encounter = _current_active_encounter(state)
    if encounter is None or encounter.status != "active" or encounter.player_presence != "engaged":
        return []
    if encounter.zone_id and save.area_snapshot.current_zone_id and encounter.zone_id != save.area_snapshot.current_zone_id:
        return []
    if encounter.sub_zone_id and save.area_snapshot.current_sub_zone_id and encounter.sub_zone_id != save.area_snapshot.current_sub_zone_id:
        return []
    if encounter.presented_at is None:
        _initialize_encounter_state(save, encounter)

    parsed_intent = _parse_player_intent(player_text)
    passive_turn = bool(parsed_intent.get("passive_turn"))
    passive_text = "【玩家旁观】玩家本轮选择观察与等待，不主动行动。"
    display_text = passive_text if passive_turn else str(parsed_intent.get("display_text") or player_text).strip()
    if any(token in display_text for token in ["离开", "逃离", "脱身", "撤退", "先撤", "转身跑", "脱离遭遇"]):
        reply = f"你暂时从《{encounter.title}》里抽身离开，但事态并未真正停下。"
        encounter.status = "escaped"
        encounter.player_presence = "away"
        encounter.latest_outcome_summary = reply
        encounter.last_advanced_at = _utc_now()
        _append_step(encounter, kind="escape_attempt", content=reply)
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "player_escapes":
                _apply_termination_updates(encounter, [{"condition_index": index, "satisfied": True}])
                break
        state.active_encounter_id = encounter.encounter_id
        _append_game_log(
            save,
            session_id,
            "encounter_escape",
            reply,
            {"encounter_id": encounter.encounter_id, "from_main_chat": True},
        )
        _touch_state(state)
        return [
            _new_scene_event(
                "encounter_progress",
                reply,
                metadata={"encounter_id": encounter.encounter_id, "encounter_title": encounter.title, "status": encounter.status},
            )
        ]

    _append_step(
        encounter,
        kind="player_action",
        actor_type="player",
        actor_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        content=display_text or gm_narration or "玩家继续应对当前遭遇。",
    )
    resolved = _ai_resolve_encounter(
        encounter,
        EncounterActRequest(
            session_id=session_id,
            encounter_id=encounter.encounter_id,
            player_prompt=f"{display_text}\nGM叙事：{gm_narration}".strip(),
            config=config,
        ),
    )
    if resolved is None:
        reply, _ = _resolve_fallback_reply(encounter, display_text or gm_narration)
        next_scene_summary, termination_updates, step_kind = _fallback_step_updates(encounter, display_text or gm_narration)
        situation_delta_hint = _fallback_situation_delta(encounter, display_text or gm_narration)
    else:
        reply = str(resolved.get("reply") or "").strip()
        next_scene_summary = str(resolved.get("scene_summary") or "").strip() or encounter.scene_summary or encounter.description
        termination_updates = resolved.get("termination_updates") if isinstance(resolved.get("termination_updates"), list) else []
        step_kind = str(resolved.get("step_kind") or "gm_update")
        situation_delta_hint = _clamp(int(resolved.get("situation_delta_hint") or 0), -8, 8)

    encounter.scene_summary = next_scene_summary
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    _append_step(encounter, kind=step_kind, content=reply)
    _apply_termination_updates(encounter, termination_updates)
    situation_delta = _clamp(situation_delta_hint + _check_bonus_from_player_prompt(player_text), -20, 20)
    if situation_delta != 0:
        encounter.situation_value = _clamp(encounter.situation_value + situation_delta, 0, 100)
        encounter.situation_trend = "improving" if situation_delta > 0 else "worsening"
    else:
        encounter.situation_trend = "stable"
    event_kind = "encounter_progress"
    outcome_package, applied_outcome_summaries = _finalize_encounter_if_needed(
        save,
        state,
        encounter,
        session_id=session_id,
    )
    if outcome_package is not None:
        event_kind = "encounter_resolution"
    else:
        encounter.status = "active"
        state.active_encounter_id = encounter.encounter_id
    state.history.append(
        EncounterResolution(
            encounter_id=encounter.encounter_id,
            player_prompt=display_text or player_text,
            reply=reply,
            time_spent_min=max(0, time_spent_min),
            quest_updates=[f"{quest_id}:progress" for quest_id in encounter.related_quest_ids],
            situation_delta=situation_delta,
            situation_value_after=encounter.situation_value,
            reputation_delta=(outcome_package.reputation_delta if outcome_package is not None else 0),
            applied_outcome_summaries=applied_outcome_summaries,
        )
    )
    state.history = state.history[-80:]
    _append_game_log(
        save,
        session_id,
        ("encounter_resolved" if event_kind == "encounter_resolution" else "encounter_progress"),
        reply,
        {"encounter_id": encounter.encounter_id, "from_main_chat": True, "time_spent_min": time_spent_min},
    )
    _touch_state(state)
    events = [
        _new_scene_event(
            "encounter_situation_update",
            f"局势值变为 {encounter.situation_value}/100，趋势为 {encounter.situation_trend}。",
            metadata={
                "encounter_id": encounter.encounter_id,
                "encounter_title": encounter.title,
                "situation_value": encounter.situation_value,
                "situation_delta": situation_delta,
            },
        ),
        _new_scene_event(
            event_kind,
            reply,
            metadata={"encounter_id": encounter.encounter_id, "encounter_title": encounter.title, "status": encounter.status},
        ),
    ]
    return events


def _legacy_unused_advance_active_encounter_in_save_v1(save, *, session_id: str, minutes_elapsed: int, config: ChatConfig | None = None) -> EncounterEntry | None:
    state = _state(save)
    encounter = _current_active_encounter(state)
    if encounter is None or encounter.player_presence != "away" or encounter.status not in {"active", "escaped"}:
        return None
    if minutes_elapsed <= 0:
        return None
    if encounter.presented_at is None:
        _initialize_encounter_state(save, encounter)

    reply = f"\u4f60\u79bb\u5f00\u73b0\u573a\u540e\uff0c\u300a{encounter.title}\u300b\u4ecd\u5728\u540e\u53f0\u63a8\u8fdb\uff0c\u5c40\u52bf\u6084\u6084\u53d1\u751f\u4e86\u53d8\u5316\u3002"
    if config is not None:
        api_key = (config.openai_api_key or "").strip()
        model = (config.model or "").strip()
        if api_key and model:
            try:
                client = create_sync_client(config, client_cls=OpenAI)
                prompt = prompt_table.render(
                    PromptKeys.ENCOUNTER_BACKGROUND_TICK_USER,
                    "\u4f60\u8981\u5728\u540e\u53f0\u63a8\u8fdb\u4e00\u4e2a\u906d\u9047\uff0c\u53ea\u80fd\u8fd4\u56de JSON\u3002\u6240\u6709\u6587\u672c\u5b57\u6bb5\u4f7f\u7528\u7b80\u4f53\u4e2d\u6587\u3002",
                    title=encounter.title,
                    description=encounter.description,
                    scene_summary=encounter.scene_summary or encounter.description,
                    termination_conditions=_termination_conditions_text(encounter),
                    recent_steps=_recent_steps_text(encounter),
                    minutes_elapsed=minutes_elapsed,
                )
                resp = client.chat.completions.create(
                    model=model,
                    **build_completion_options(config),
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": prompt_table.get_text("encounter.generate.system", "\u4f60\u53ea\u8f93\u51fa JSON\u3002\u6240\u6709\u6587\u672c\u5b57\u6bb5\u4f7f\u7528\u7b80\u4f53\u4e2d\u6587\u3002")},
                        {"role": "user", "content": prompt},
                    ],
                )
                parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
                reply = _force_chinese_text(parsed.get("reply"), reply, limit=240)
                encounter.scene_summary = _force_chinese_text(
                    parsed.get("scene_summary"),
                    encounter.scene_summary or encounter.description,
                    limit=240,
                )
                _apply_termination_updates(encounter, parsed.get("termination_updates"))
            except Exception:
                pass

    encounter.background_tick_count += 1
    background_delta = -_clamp(max(1, minutes_elapsed // 10), 1, 6)
    encounter.situation_value = _clamp(encounter.situation_value + background_delta, 0, 100)
    encounter.situation_trend = "worsening" if background_delta < 0 else "stable"
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    _append_step(encounter, kind="background_tick", content=reply)
    _finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
    _append_game_log(
        save,
        session_id,
        "encounter_background_tick",
        reply,
        {
            "encounter_id": encounter.encounter_id,
            "minutes_elapsed": minutes_elapsed,
            "situation_value": encounter.situation_value,
            "situation_delta": background_delta,
        },
    )
    _touch_state(state)
    return encounter


def _legacy_unused_apply_active_encounter_situation_delta_in_save_v1(
    save,
    *,
    session_id: str,
    delta: int,
    summary: str,
    actor_role_id: str = "",
    actor_name: str = "",
) -> list:
    state = _state(save)
    encounter = _current_active_encounter(state)
    if encounter is None or encounter.status not in {"active", "escaped"}:
        return []
    if encounter.presented_at is None:
        _initialize_encounter_state(save, encounter)
    applied = _clamp(delta, -20, 20)
    if applied == 0:
        return []
    encounter.situation_value = _clamp(encounter.situation_value + applied, 0, 100)
    encounter.situation_trend = "improving" if applied > 0 else "worsening"
    encounter.latest_outcome_summary = (summary or encounter.latest_outcome_summary or encounter.scene_summary or encounter.description)[:240]
    encounter.last_advanced_at = _utc_now()
    _append_step(
        encounter,
        kind=("team_reaction" if actor_role_id and any(item.role_id == actor_role_id for item in getattr(save.team_state, "members", [])) else "npc_reaction"),
        actor_type=("team" if actor_role_id and any(item.role_id == actor_role_id for item in getattr(save.team_state, "members", [])) else "npc"),
        actor_id=actor_role_id,
        actor_name=actor_name,
        content=encounter.latest_outcome_summary,
    )
    outcome_package, _ = _finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
    _append_game_log(
        save,
        session_id,
        "encounter_situation_update",
        encounter.latest_outcome_summary,
        {
            "encounter_id": encounter.encounter_id,
            "situation_value": encounter.situation_value,
            "situation_delta": applied,
        },
    )
    events = [
        _new_scene_event(
            "encounter_situation_update",
            f"局势值变为 {encounter.situation_value}/100，趋势为 {encounter.situation_trend}。",
            actor_role_id=actor_role_id,
            actor_name=actor_name,
            metadata={
                "encounter_id": encounter.encounter_id,
                "encounter_title": encounter.title,
                "situation_value": encounter.situation_value,
                "situation_delta": applied,
            },
        )
    ]
    if outcome_package is not None:
        events.append(
            _new_scene_event(
                "encounter_resolution",
                outcome_package.narrative_summary or encounter.latest_outcome_summary or encounter.scene_summary or encounter.description,
                metadata={
                    "encounter_id": encounter.encounter_id,
                    "encounter_title": encounter.title,
                    "status": encounter.status,
                },
            )
        )
    return events


def escape_encounter(encounter_id: str, req: EncounterEscapeRequest) -> EncounterEscapeResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    encounter = _find_encounter(state, encounter_id)
    if encounter.status != "active" or encounter.player_presence != "engaged":
        raise ValueError("ENCOUNTER_INVALID_STATUS")

    from app.models.schemas import ActionCheckRequest
    from app.services.world_service import action_check

    action_result: ActionCheckResponse = action_check(
        ActionCheckRequest(
            session_id=req.session_id,
            action_type="check",
            action_prompt=f"encounter_escape; encounter_id={encounter.encounter_id}; title={encounter.title}",
            actor_role_id=save.player_static_data.player_id,
            allow_backend_roll=True,
            config=req.config,
        )
    )
    escape_success = bool(action_result.success)
    if escape_success:
        encounter.status = "escaped"
        encounter.player_presence = "away"
        state.active_encounter_id = encounter.encounter_id
        reply = f"你暂时从《{encounter.title}》里抽身离开，但事件仍在你身后继续发展。"
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "player_escapes":
                _apply_termination_updates(encounter, [{"condition_index": index, "satisfied": True}])
                break
    else:
        reply = f"你试图从《{encounter.title}》里脱身，但局势没有给你留下完整的脱离空档。"
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    _append_step(encounter, kind="escape_attempt", content=reply)
    _append_game_log(
        save,
        req.session_id,
        "encounter_escape",
        reply,
        {"encounter_id": encounter.encounter_id, "escape_success": escape_success},
    )
    _touch_state(state)
    save_current(save)
    return EncounterEscapeResponse(
        session_id=req.session_id,
        encounter_id=encounter.encounter_id,
        status=encounter.status,
        reply=reply,
        time_spent_min=action_result.time_spent_min,
        escape_success=escape_success,
        encounter=encounter,
        encounter_state=state,
        action_check=action_result,
    )


def rejoin_encounter(encounter_id: str, req: EncounterRejoinRequest) -> EncounterRejoinResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    encounter = _find_encounter(state, encounter_id)
    if encounter.status not in {"active", "escaped"} or encounter.player_presence != "away":
        raise ValueError("ENCOUNTER_INVALID_STATUS")
    if encounter.zone_id != save.area_snapshot.current_zone_id or encounter.sub_zone_id != save.area_snapshot.current_sub_zone_id:
        raise ValueError("ENCOUNTER_REJOIN_AREA_MISMATCH")

    reply = f"你重新回到了《{encounter.title}》发生的地点，局势再次把你卷了进去。"
    encounter.status = "active"
    encounter.player_presence = "engaged"
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    state.active_encounter_id = encounter.encounter_id
    _append_step(encounter, kind="gm_update", content=reply)
    _touch_state(state)
    save_current(save)
    return EncounterRejoinResponse(
        session_id=req.session_id,
        encounter_id=encounter.encounter_id,
        status=encounter.status,
        reply=reply,
        encounter=encounter,
        encounter_state=state,
    )


def _legacy_unused_get_encounter_debug_overview_v1(session_id: str) -> EncounterDebugOverviewResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    state = _state(save)
    active = _current_active_encounter(state)
    queued = _pending_entries(state)
    if active is not None:
        summary = f"当前活跃遭遇: {active.title} / {active.status} / {active.player_presence}"
    elif queued:
        summary = f"待处理遭遇数: {len(queued)}"
    else:
        summary = "当前没有活跃或待处理遭遇。"
    return EncounterDebugOverviewResponse(
        session_id=session_id,
        active_encounter=active,
        queued_encounters=queued,
        summary=summary,
    )


def _concretize_encounter_reply(
    encounter: EncounterEntry,
    player_prompt: str,
    *,
    reply: str,
    scene_summary: str,
    specific_change: str = "",
    specific_threat: str = "",
    opened_opportunity: str = "",
) -> tuple[str, str]:
    from app.services.encounter_runtime_v2 import concretize_encounter_reply

    save = get_current_save(default_session_id=getattr(encounter, "encounter_id", "") or "encounter_runtime")
    return concretize_encounter_reply(
        save,
        encounter,
        player_prompt,
        reply=reply,
        scene_summary=scene_summary,
        specific_change=specific_change,
        specific_threat=specific_threat,
        opened_opportunity=opened_opportunity,
    )


def _resolve_fallback_reply(encounter: EncounterEntry, player_prompt: str) -> tuple[str, int]:
    from app.services.encounter_runtime_v2 import resolve_fallback_reply

    save = get_current_save(default_session_id=getattr(encounter, "encounter_id", "") or "encounter_runtime")
    return resolve_fallback_reply(save, encounter, player_prompt)


def _ai_resolve_encounter(encounter: EncounterEntry, req: EncounterActRequest) -> dict[str, object] | None:
    from app.services.encounter_runtime_v2 import ai_resolve_encounter

    return ai_resolve_encounter(encounter, req)


def _fallback_step_updates(encounter: EncounterEntry, player_prompt: str) -> tuple[str, list[dict[str, object]], str]:
    from app.services.encounter_runtime_v2 import fallback_step_updates

    return fallback_step_updates(encounter, player_prompt)


def advance_active_encounter_in_save(save, *, session_id: str, minutes_elapsed: int, config: ChatConfig | None = None) -> EncounterEntry | None:
    from app.services.encounter_runtime_v2 import advance_active_encounter_in_save as runtime_v2

    return runtime_v2(save, session_id=session_id, minutes_elapsed=minutes_elapsed, config=config)


def apply_active_encounter_situation_delta_in_save(
    save,
    *,
    session_id: str,
    delta: int,
    summary: str,
    actor_role_id: str = "",
    actor_name: str = "",
) -> list:
    from app.services.encounter_runtime_v2 import apply_active_encounter_situation_delta_in_save as runtime_v2

    return runtime_v2(
        save,
        session_id=session_id,
        delta=delta,
        summary=summary,
        actor_role_id=actor_role_id,
        actor_name=actor_name,
    )


def advance_active_encounter_from_main_chat_in_save(
    save,
    *,
    session_id: str,
    player_text: str,
    gm_narration: str,
    time_spent_min: int,
    config: ChatConfig | None = None,
) -> list:
    from app.services.encounter_runtime_v2 import advance_active_encounter_from_main_chat_in_save as runtime_v2

    return runtime_v2(
        save,
        session_id=session_id,
        player_text=player_text,
        gm_narration=gm_narration,
        time_spent_min=time_spent_min,
        config=config,
    )


def get_encounter_debug_overview(session_id: str) -> EncounterDebugOverviewResponse:
    from app.services.encounter_runtime_v2 import get_encounter_debug_overview as runtime_v2

    return runtime_v2(session_id)


def _legacy_unused_advance_active_encounter_in_save_v2(save, *, session_id: str, minutes_elapsed: int, config: ChatConfig | None = None) -> EncounterEntry | None:
    state = _state(save)
    encounter = _current_active_encounter(state)
    if encounter is None or encounter.player_presence != "away" or encounter.status not in {"active", "escaped"}:
        return None
    if minutes_elapsed <= 0:
        return None
    if encounter.presented_at is None:
        _initialize_encounter_state(save, encounter)

    team_members, visible_npcs = _visible_participant_text(save, encounter)
    raw_reply = f"你离开现场后，《{encounter.title}》仍在后台推进。"
    raw_scene_summary = encounter.scene_summary or encounter.description
    if config is not None:
        api_key = (config.openai_api_key or "").strip()
        model = (config.model or "").strip()
        if api_key and model:
            try:
                client = create_sync_client(config, client_cls=OpenAI)
                prompt = prompt_table.render(
                    PromptKeys.ENCOUNTER_BACKGROUND_TICK_USER,
                    "你要在后台推进一个遭遇，只能返回 JSON。reply 和 scene_summary 必须具体说明现场哪一处发生了什么变化、风险是什么、接下来会压向哪里。",
                    title=encounter.title,
                    description=encounter.description,
                    scene_summary=encounter.scene_summary or encounter.description,
                    termination_conditions=_termination_conditions_text(encounter),
                    recent_steps=_recent_steps_text(encounter),
                    minutes_elapsed=minutes_elapsed,
                    team_members=team_members,
                    visible_npcs=visible_npcs,
                )
                resp = client.chat.completions.create(
                    model=model,
                    **build_completion_options(config),
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": prompt_table.get_text("encounter.generate.system", "你只输出 JSON。所有文本字段使用简体中文。")},
                        {"role": "user", "content": prompt},
                    ],
                )
                parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
                raw_reply = str(parsed.get("reply") or raw_reply)
                raw_scene_summary = str(parsed.get("scene_summary") or raw_scene_summary)
                _apply_termination_updates(encounter, parsed.get("termination_updates"))
            except Exception:
                pass

    reply, next_scene_summary = _concretize_encounter_reply(
        encounter,
        f"后台推进 {minutes_elapsed} 分钟",
        reply=raw_reply,
        scene_summary=raw_scene_summary,
    )
    encounter.scene_summary = next_scene_summary
    encounter.background_tick_count += 1
    background_delta = -_clamp(max(1, minutes_elapsed // 10), 1, 6)
    encounter.situation_value = _clamp(encounter.situation_value + background_delta, 0, 100)
    encounter.situation_trend = "worsening" if background_delta < 0 else "stable"
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    _append_step(encounter, kind="background_tick", content=reply)
    _finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
    _append_game_log(
        save,
        session_id,
        "encounter_background_tick",
        reply,
        {
            "encounter_id": encounter.encounter_id,
            "minutes_elapsed": minutes_elapsed,
            "situation_value": encounter.situation_value,
            "situation_delta": background_delta,
        },
    )
    _touch_state(state)
    return encounter


def _legacy_unused_apply_active_encounter_situation_delta_in_save_v2(
    save,
    *,
    session_id: str,
    delta: int,
    summary: str,
    actor_role_id: str = "",
    actor_name: str = "",
) -> list:
    state = _state(save)
    encounter = _current_active_encounter(state)
    if encounter is None or encounter.status not in {"active", "escaped"}:
        return []
    if encounter.presented_at is None:
        _initialize_encounter_state(save, encounter)
    applied = _clamp(delta, -20, 20)
    if applied == 0:
        return []

    team_member = next((item for item in getattr(save.team_state, "members", []) if item.role_id == actor_role_id), None)
    temp_npc = next((item for item in getattr(encounter, "temporary_npcs", []) or [] if item.encounter_npc_id == actor_role_id), None)
    if team_member is not None:
        step_kind = "team_reaction"
        actor_type = "team"
    elif temp_npc is not None:
        step_kind = "temp_npc_action"
        actor_type = "encounter_temp_npc"
        actor_name = actor_name or temp_npc.name
    elif actor_role_id:
        step_kind = "npc_reaction"
        actor_type = "npc"
    else:
        step_kind = "background_tick"
        actor_type = "system"

    encounter.situation_value = _clamp(encounter.situation_value + applied, 0, 100)
    encounter.situation_trend = "improving" if applied > 0 else "worsening"
    concrete_summary, next_scene_summary = _concretize_encounter_reply(
        encounter,
        summary or "局势推进",
        reply=summary or encounter.latest_outcome_summary or encounter.scene_summary or encounter.description,
        scene_summary=encounter.scene_summary or encounter.description,
    )
    encounter.scene_summary = next_scene_summary
    encounter.latest_outcome_summary = concrete_summary
    encounter.last_advanced_at = _utc_now()
    _append_step(
        encounter,
        kind=step_kind,
        actor_type=actor_type,
        actor_id=actor_role_id,
        actor_name=actor_name,
        content=concrete_summary,
    )
    outcome_package, _ = _finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
    _append_game_log(
        save,
        session_id,
        "encounter_situation_update",
        concrete_summary,
        {
            "encounter_id": encounter.encounter_id,
            "situation_value": encounter.situation_value,
            "situation_delta": applied,
        },
    )
    events = [
        _new_scene_event(
            "encounter_situation_update",
            f"局势值变为 {encounter.situation_value}/100，趋势为 {encounter.situation_trend}。{concrete_summary}",
            actor_role_id=actor_role_id,
            actor_name=actor_name,
            metadata={
                "encounter_id": encounter.encounter_id,
                "encounter_title": encounter.title,
                "situation_value": encounter.situation_value,
                "situation_delta": applied,
                "actor_type": actor_type,
            },
        )
    ]
    if outcome_package is not None:
        events.append(
            _new_scene_event(
                "encounter_resolution",
                outcome_package.narrative_summary or concrete_summary,
                metadata={
                    "encounter_id": encounter.encounter_id,
                    "encounter_title": encounter.title,
                    "status": encounter.status,
                },
            )
        )
    return events


def _legacy_unused_advance_active_encounter_from_main_chat_in_save_v2(
    save,
    *,
    session_id: str,
    player_text: str,
    gm_narration: str,
    time_spent_min: int,
    config: ChatConfig | None = None,
) -> list:
    state = _state(save)
    encounter = _current_active_encounter(state)
    if encounter is None or encounter.status != "active" or encounter.player_presence != "engaged":
        return []
    if encounter.zone_id and save.area_snapshot.current_zone_id and encounter.zone_id != save.area_snapshot.current_zone_id:
        return []
    if encounter.sub_zone_id and save.area_snapshot.current_sub_zone_id and encounter.sub_zone_id != save.area_snapshot.current_sub_zone_id:
        return []
    if encounter.presented_at is None:
        _initialize_encounter_state(save, encounter)

    parsed_intent = _parse_player_intent(player_text)
    passive_turn = bool(parsed_intent.get("passive_turn"))
    passive_text = "【玩家旁观】玩家本轮选择观察与等待，不主动行动。"
    display_text = passive_text if passive_turn else str(parsed_intent.get("display_text") or player_text).strip()
    if any(token in display_text for token in ["离开", "逃离", "脱身", "撤退", "先撤", "转身跑", "脱离遭遇"]):
        reply = f"你暂时从《{encounter.title}》里抽身离开，但现场问题仍在继续发展。"
        encounter.status = "escaped"
        encounter.player_presence = "away"
        encounter.latest_outcome_summary = reply
        encounter.last_advanced_at = _utc_now()
        _append_step(encounter, kind="escape_attempt", content=reply)
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "player_escapes":
                _apply_termination_updates(encounter, [{"condition_index": index, "satisfied": True}])
                break
        state.active_encounter_id = encounter.encounter_id
        _append_game_log(save, session_id, "encounter_escape", reply, {"encounter_id": encounter.encounter_id, "from_main_chat": True})
        _touch_state(state)
        return [
            _new_scene_event(
                "encounter_progress",
                reply,
                metadata={"encounter_id": encounter.encounter_id, "encounter_title": encounter.title, "status": encounter.status},
            )
        ]

    _append_step(
        encounter,
        kind="player_action",
        actor_type="player",
        actor_id=save.player_static_data.player_id,
        actor_name=save.player_static_data.name,
        content=display_text or gm_narration or "玩家继续应对当前遭遇。",
    )
    resolved = _ai_resolve_encounter(
        encounter,
        EncounterActRequest(
            session_id=session_id,
            encounter_id=encounter.encounter_id,
            player_prompt=f"{display_text}\nGM叙事：{gm_narration}".strip(),
            config=config,
        ),
    )
    if resolved is None:
        reply, _ = _resolve_fallback_reply(encounter, display_text or gm_narration)
        next_scene_summary, termination_updates, step_kind = _fallback_step_updates(encounter, display_text or gm_narration)
        situation_delta_hint = _fallback_situation_delta(encounter, display_text or gm_narration)
    else:
        reply = str(resolved.get("reply") or "").strip()
        next_scene_summary = str(resolved.get("scene_summary") or "").strip() or encounter.scene_summary or encounter.description
        termination_updates = resolved.get("termination_updates") if isinstance(resolved.get("termination_updates"), list) else []
        step_kind = str(resolved.get("step_kind") or "gm_update")
        situation_delta_hint = _clamp(int(resolved.get("situation_delta_hint") or 0), -8, 8)

    encounter.scene_summary = next_scene_summary
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    _append_step(encounter, kind=step_kind, content=reply)
    _apply_termination_updates(encounter, termination_updates)
    situation_delta = _clamp(situation_delta_hint + _check_bonus_from_player_prompt(player_text), -20, 20)
    if situation_delta != 0:
        encounter.situation_value = _clamp(encounter.situation_value + situation_delta, 0, 100)
        encounter.situation_trend = "improving" if situation_delta > 0 else "worsening"
    else:
        encounter.situation_trend = "stable"
    event_kind = "encounter_progress"
    outcome_package, applied_outcome_summaries = _finalize_encounter_if_needed(save, state, encounter, session_id=session_id)
    if outcome_package is not None:
        event_kind = "encounter_resolution"
    else:
        encounter.status = "active"
        state.active_encounter_id = encounter.encounter_id
    state.history.append(
        EncounterResolution(
            encounter_id=encounter.encounter_id,
            player_prompt=display_text or player_text,
            reply=reply,
            time_spent_min=max(0, time_spent_min),
            quest_updates=[f"{quest_id}:progress" for quest_id in encounter.related_quest_ids],
            situation_delta=situation_delta,
            situation_value_after=encounter.situation_value,
            reputation_delta=(outcome_package.reputation_delta if outcome_package is not None else 0),
            applied_outcome_summaries=applied_outcome_summaries,
        )
    )
    state.history = state.history[-80:]
    _append_game_log(
        save,
        session_id,
        ("encounter_resolved" if event_kind == "encounter_resolution" else "encounter_progress"),
        reply,
        {"encounter_id": encounter.encounter_id, "from_main_chat": True, "time_spent_min": time_spent_min},
    )
    _touch_state(state)
    events = [
        _new_scene_event(
            "encounter_situation_update",
            f"局势值变为 {encounter.situation_value}/100，趋势为 {encounter.situation_trend}。{reply}",
            metadata={
                "encounter_id": encounter.encounter_id,
                "encounter_title": encounter.title,
                "situation_value": encounter.situation_value,
                "situation_delta": situation_delta,
            },
        ),
        _new_scene_event(
            event_kind,
            reply,
            metadata={"encounter_id": encounter.encounter_id, "encounter_title": encounter.title, "status": encounter.status},
        ),
    ]
    return events


def _legacy_unused_escape_encounter_v1(encounter_id: str, req: EncounterEscapeRequest) -> EncounterEscapeResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    encounter = _find_encounter(state, encounter_id)
    if encounter.status != "active" or encounter.player_presence != "engaged":
        raise ValueError("ENCOUNTER_INVALID_STATUS")
    if encounter.presented_at is None:
        _initialize_encounter_state(save, encounter)

    from app.models.schemas import ActionCheckRequest
    from app.services.world_service import action_check

    action_result: ActionCheckResponse = action_check(
        ActionCheckRequest(
            session_id=req.session_id,
            action_type="check",
            action_prompt=f"encounter_escape; encounter_id={encounter.encounter_id}; title={encounter.title}",
            actor_role_id=save.player_static_data.player_id,
            allow_backend_roll=True,
            config=req.config,
        )
    )
    escape_success = bool(action_result.success)
    if escape_success:
        encounter.status = "escaped"
        encounter.player_presence = "away"
        state.active_encounter_id = encounter.encounter_id
        encounter.situation_value = _clamp(encounter.situation_value + 4, 0, 100)
        encounter.situation_trend = "improving"
        reply = f"你暂时从《{encounter.title}》里抽身离开，但事情还在你身后继续发展。"
        for index, condition in enumerate(encounter.termination_conditions):
            if condition.kind == "player_escapes":
                _apply_termination_updates(encounter, [{"condition_index": index, "satisfied": True}])
                break
    else:
        encounter.situation_value = _clamp(encounter.situation_value - 4, 0, 100)
        encounter.situation_trend = "worsening"
        reply = f"你试图从《{encounter.title}》里脱身，但局势没有给你留下完整的脱离空档。"
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    _append_step(encounter, kind="escape_attempt", content=reply)
    _append_game_log(
        save,
        req.session_id,
        "encounter_escape",
        reply,
        {
            "encounter_id": encounter.encounter_id,
            "escape_success": escape_success,
            "situation_value": encounter.situation_value,
        },
    )
    _touch_state(state)
    save_current(save)
    return EncounterEscapeResponse(
        session_id=req.session_id,
        encounter_id=encounter.encounter_id,
        status=encounter.status,
        reply=reply,
        time_spent_min=action_result.time_spent_min,
        escape_success=escape_success,
        encounter=encounter,
        encounter_state=state,
        action_check=action_result,
    )


def _legacy_unused_rejoin_encounter_v1(encounter_id: str, req: EncounterRejoinRequest) -> EncounterRejoinResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = _state(save)
    encounter = _find_encounter(state, encounter_id)
    if encounter.status not in {"active", "escaped"} or encounter.player_presence != "away":
        raise ValueError("ENCOUNTER_INVALID_STATUS")
    if encounter.zone_id != save.area_snapshot.current_zone_id or encounter.sub_zone_id != save.area_snapshot.current_sub_zone_id:
        raise ValueError("ENCOUNTER_REJOIN_AREA_MISMATCH")
    if encounter.presented_at is None:
        _initialize_encounter_state(save, encounter)

    reply = f"你重新回到了《{encounter.title}》发生的地点，局势再次把你卷了进去。"
    encounter.status = "active"
    encounter.player_presence = "engaged"
    encounter.situation_value = _clamp(encounter.situation_value + 2, 0, 100)
    encounter.situation_trend = "improving"
    encounter.latest_outcome_summary = reply
    encounter.last_advanced_at = _utc_now()
    state.active_encounter_id = encounter.encounter_id
    _append_step(encounter, kind="gm_update", content=reply)
    _touch_state(state)
    save_current(save)
    return EncounterRejoinResponse(
        session_id=req.session_id,
        encounter_id=encounter.encounter_id,
        status=encounter.status,
        reply=reply,
        encounter=encounter,
        encounter_state=state,
    )


def _legacy_unused_get_encounter_debug_overview_v2(session_id: str) -> EncounterDebugOverviewResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    state = _state(save)
    active = _current_active_encounter(state)
    queued = _pending_entries(state)
    if active is not None:
        summary = f"当前活跃遭遇: {active.title} / {active.status} / {active.player_presence} / 局势 {active.situation_value}/100"
    elif queued:
        summary = f"待处理遭遇数: {len(queued)}"
    else:
        summary = "当前没有活跃或待处理遭遇。"
    return EncounterDebugOverviewResponse(
        session_id=session_id,
        active_encounter=active,
        queued_encounters=queued,
        summary=summary,
    )
