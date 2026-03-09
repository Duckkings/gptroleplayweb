from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Iterable

from openai import OpenAI

from app.core.prompt_keys import PromptKeys
from app.core.prompt_table import prompt_table
from app.core.token_usage import token_usage_store
from app.models.schemas import (
    AreaNpc,
    GameLogEntry,
    NpcRoleCard,
    PlayerStaticData,
    RoleRelation,
    TeamChatReply,
    TeamChatRequest,
    TeamChatResponse,
    TeamDebugGenerateRequest,
    TeamInviteRequest,
    TeamLeaveRequest,
    TeamMember,
    TeamMutationResponse,
    TeamReaction,
    TeamState,
    TeamStateResponse,
)
from app.services.ai_adapter import build_completion_options, create_sync_client
from app.services.consistency_service import build_npc_knowledge_snapshot
from app.services.world_service import (
    _ability_mod,
    _ability_score_with_seed,
    _compose_npc_reply,
    _append_npc_dialogue,
    _build_npc_context,
    _build_npc_prompt_context,
    _build_npc_roleplay_brief,
    _build_npc_flavor,
    _build_npc_likes,
    _build_npc_profile,
    _build_npc_talkative_maximum,
    _class_template,
    _default_world_clock,
    _ensure_npc_role_complete,
    _extract_json_content,
    _make_npc_item,
    _pick_many,
    _recompute_player_derived,
    _stable_int,
    _world_time_payload,
    apply_speech_time,
    get_current_save,
    save_current,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"


def _touch_state(state: TeamState) -> None:
    state.updated_at = _utc_now()


def ensure_team_state(save) -> TeamState:
    state = getattr(save, "team_state", None)
    if state is None:
        save.team_state = TeamState()
        return save.team_state
    if len(state.reactions) > 100:
        state.reactions = state.reactions[-100:]
    return state


def _current_player_area(save) -> tuple[str | None, str | None]:
    zone_id = save.area_snapshot.current_zone_id
    sub_zone_id = save.area_snapshot.current_sub_zone_id
    if not zone_id and save.player_runtime_data.current_position is not None:
        zone_id = save.player_runtime_data.current_position.zone_id
    return zone_id, sub_zone_id


def _current_player_area_names(save) -> tuple[str, str]:
    zone_id, sub_zone_id = _current_player_area(save)
    zone_name = next((item.name for item in save.area_snapshot.zones if item.zone_id == zone_id), zone_id or "当前区域")
    sub_name = next((item.name for item in save.area_snapshot.sub_zones if item.sub_zone_id == sub_zone_id), sub_zone_id or "附近")
    return zone_name, sub_name


def _find_role(save, role_id: str) -> NpcRoleCard:
    role = next((item for item in save.role_pool if item.role_id == role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    return role


def _find_member(state: TeamState, role_id: str) -> TeamMember | None:
    return next((item for item in state.members if item.role_id == role_id), None)


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


def _remove_area_presence(save, role_id: str) -> None:
    for sub in save.area_snapshot.sub_zones:
        sub.npcs = [item for item in sub.npcs if item.npc_id != role_id]


def _restore_area_presence(save, role: NpcRoleCard, member: TeamMember) -> None:
    role.zone_id = member.origin_zone_id
    role.sub_zone_id = member.origin_sub_zone_id
    role.state = "idle"
    if not member.origin_sub_zone_id:
        return
    sub = next((item for item in save.area_snapshot.sub_zones if item.sub_zone_id == member.origin_sub_zone_id), None)
    if sub is None:
        return
    if not any(item.npc_id == role.role_id for item in sub.npcs):
        sub.npcs.append(AreaNpc(npc_id=role.role_id, name=role.name, state="idle"))


def _player_relation_tag(role: NpcRoleCard, player_id: str) -> str:
    relation = next((item for item in role.relations if item.target_role_id == player_id), None)
    return relation.relation_tag if relation is not None else "neutral"


def _relation_scores(tag: str) -> tuple[int, int]:
    mapping = {
        "hostile": (5, 5),
        "wary": (20, 15),
        "neutral": (45, 35),
        "met": (50, 40),
        "friendly": (70, 60),
        "ally": (85, 80),
    }
    return mapping.get(tag.strip().lower(), (45, 35))


def _build_invite_decision(save, role: NpcRoleCard, req: TeamInviteRequest) -> tuple[bool, str, int, int]:
    relation_tag = _player_relation_tag(role, save.player_static_data.player_id)
    base_affinity, base_trust = _relation_scores(relation_tag)
    prompt = req.player_prompt.strip()
    positive = any(token in prompt.lower() for token in ["help", "together", "team", "protect", "合作", "帮", "一起", "同行"])
    negative = any(token in prompt.lower() for token in ["threat", "force", "order", "滚", "命令", "威胁", "逼"])
    if positive:
        base_affinity = min(100, base_affinity + 8)
        base_trust = min(100, base_trust + 6)
    if negative:
        base_affinity = max(0, base_affinity - 20)
        base_trust = max(0, base_trust - 20)

    config = req.config
    if config is not None:
        api_key = (config.openai_api_key or "").strip()
        model = (config.model or "").strip()
        if api_key and model:
            try:
                client = create_sync_client(config, client_cls=OpenAI)
                zone_name, sub_name = _current_player_area_names(save)
                prompt_text = (
                    "You decide whether one NPC should join the player's party. Return JSON only.\n"
                    "Schema: {\"accept\":true,\"reason\":\"\",\"affinity\":50,\"trust\":40}.\n"
                    "Consider personality, relation tag, trust, and whether interests align.\n"
                    f"NPC={role.name}, personality={role.personality}, background={role.background}, cognition={role.cognition}, alignment={role.alignment}.\n"
                    f"CurrentArea={zone_name}/{sub_name}. RelationTag={relation_tag}. PlayerRequest={prompt or 'none'}.\n"
                    "affinity/trust must be integers between 0 and 100."
                )
                resp = client.chat.completions.create(
                    model=model,
                    **build_completion_options(config),
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": "Return JSON only."},
                        {"role": "user", "content": prompt_text},
                    ],
                )
                parsed = json.loads((resp.choices[0].message.content or "{}").strip())
                accept = bool(parsed.get("accept"))
                reason = str(parsed.get("reason") or "").strip()
                affinity = max(0, min(100, int(parsed.get("affinity") or base_affinity)))
                trust = max(0, min(100, int(parsed.get("trust") or base_trust)))
                if reason:
                    return accept, reason, affinity, trust
                return accept, ("对你的邀请点了头。" if accept else "摇头拒绝了你的邀请。"), affinity, trust
            except Exception:
                pass

    accept = base_affinity >= 45 and base_trust >= 30
    if accept:
        return True, "经过短暂考虑后同意与你同行。", base_affinity, base_trust
    return False, "觉得现在还不适合把命运交到你手上。", base_affinity, base_trust


def sync_team_members_with_player_in_save(save) -> bool:
    state = ensure_team_state(save)
    zone_id, sub_zone_id = _current_player_area(save)
    changed = False
    for member in state.members:
        role = next((item for item in save.role_pool if item.role_id == member.role_id), None)
        if role is None:
            continue
        if role.zone_id != zone_id:
            role.zone_id = zone_id
            changed = True
        if role.sub_zone_id != sub_zone_id:
            role.sub_zone_id = sub_zone_id
            changed = True
        if role.state != "in_team":
            role.state = "in_team"
            changed = True
        if _ensure_npc_role_complete(save, role):
            changed = True
        _remove_area_presence(save, role.role_id)
    if changed:
        _touch_state(state)
    return changed


def get_team_state(session_id: str) -> TeamStateResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    state = ensure_team_state(save)
    sync_team_members_with_player_in_save(save)
    save_current(save)
    return TeamStateResponse(session_id=session_id, team_state=state, members=state.members)


def _remove_member_from_team_in_save(save, member: TeamMember, reason: str) -> tuple[TeamMember, NpcRoleCard | None]:
    state = ensure_team_state(save)
    role = next((item for item in save.role_pool if item.role_id == member.role_id), None)
    if role is not None:
        if member.is_debug:
            _remove_area_presence(save, role.role_id)
            save.role_pool = [item for item in save.role_pool if item.role_id != role.role_id]
            role = None
        else:
            _restore_area_presence(save, role, member)
    state.members = [item for item in state.members if item.role_id != member.role_id]
    _append_game_log(
        save,
        save.session_id,
        "team_leave",
        f"{member.name} 离开了队伍。",
        {"role_id": member.role_id, "reason": reason or "manual"},
    )
    _touch_state(state)
    return member, role


def invite_npc_to_team(req: TeamInviteRequest) -> TeamMutationResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = ensure_team_state(save)
    role = _find_role(save, req.npc_role_id)
    current = _find_member(state, role.role_id)
    if current is not None:
        return TeamMutationResponse(
            session_id=req.session_id,
            team_state=state,
            member=current,
            role=role,
            accepted=True,
            chat_feedback=f"{role.name} 已经在队伍中。",
        )

    accepted, reason, affinity, trust = _build_invite_decision(save, role, req)
    if not accepted:
        _append_game_log(
            save,
            req.session_id,
            "team_invite_rejected",
            f"{role.name} 拒绝加入队伍。",
            {"role_id": role.role_id},
        )
        save_current(save)
        return TeamMutationResponse(
            session_id=req.session_id,
            team_state=state,
            role=role,
            accepted=False,
            chat_feedback=f"{role.name}{reason}",
        )

    member = TeamMember(
        role_id=role.role_id,
        name=role.name,
        origin_zone_id=role.zone_id,
        origin_sub_zone_id=role.sub_zone_id,
        affinity=affinity,
        trust=trust,
        join_source="story",
        join_reason=reason,
    )
    state.members.append(member)
    role.state = "in_team"
    _ensure_npc_role_complete(save, role)
    sync_team_members_with_player_in_save(save)
    _remove_area_presence(save, role.role_id)
    relation = next((item for item in role.relations if item.target_role_id == save.player_static_data.player_id), None)
    if relation is None:
        role.relations.append(RoleRelation(target_role_id=save.player_static_data.player_id, relation_tag="friendly", note="加入队伍"))
    _append_game_log(
        save,
        req.session_id,
        "team_join",
        f"{role.name} 加入了队伍。",
        {"role_id": role.role_id, "affinity": affinity, "trust": trust},
    )
    _touch_state(state)
    save_current(save)
    return TeamMutationResponse(
        session_id=req.session_id,
        team_state=state,
        member=member,
        role=role,
        accepted=True,
        chat_feedback=f"{role.name}{reason}",
    )


def leave_npc_from_team(req: TeamLeaveRequest) -> TeamMutationResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = ensure_team_state(save)
    member = _find_member(state, req.npc_role_id)
    if member is None:
        raise KeyError("TEAM_MEMBER_NOT_FOUND")
    removed, role = _remove_member_from_team_in_save(save, member, req.reason or "manual")
    save_current(save)
    return TeamMutationResponse(
        session_id=req.session_id,
        team_state=state,
        member=removed,
        role=role,
        accepted=True,
        chat_feedback=f"{removed.name} 已离开队伍。",
    )


def _fallback_debug_role(save, prompt: str) -> NpcRoleCard:
    zone_name, sub_name = _current_player_area_names(save)
    role_id = _new_id("debug_team")
    name_seed = prompt.strip()[:8] or "调试队友"
    name = f"{name_seed}队友"
    role = NpcRoleCard(
        role_id=role_id,
        name=name,
        zone_id=_current_player_area(save)[0],
        sub_zone_id=_current_player_area(save)[1],
        state="in_team",
        personality="机敏",
        speaking_style="说话简短直接",
        appearance="带着旅行装备",
        background=f"由调试入口生成，当前跟随你在【{zone_name}/{sub_name}】行动。",
        cognition="重视同伴承诺",
        alignment="neutral_good",
        profile=_build_npc_profile(role_id, name),
    )
    role.profile.name = name
    role.profile.role_type = "npc"
    _recompute_player_derived(role.profile)
    return role


def _build_debug_team_role(save, prompt: str) -> NpcRoleCard:
    zone_name, sub_name = _current_player_area_names(save)
    role_id = _new_id("debug_team")
    name_seed = prompt.strip()[:8] or "调试队友"
    name = f"{name_seed}队友"
    flavor = _build_npc_flavor(role_id, zone_name, sub_name, "由 Debug 面板生成并暂时跟随玩家。")
    talkative_maximum = _build_npc_talkative_maximum(role_id, flavor["personality"])
    role = NpcRoleCard(
        role_id=role_id,
        name=name,
        zone_id=_current_player_area(save)[0],
        sub_zone_id=_current_player_area(save)[1],
        state="in_team",
        personality=flavor["personality"],
        speaking_style=flavor["speaking_style"],
        appearance=flavor["appearance"],
        background=flavor["background"],
        cognition=flavor["cognition"],
        alignment=flavor["alignment"],
        secret=flavor["secret"],
        likes=_build_npc_likes(role_id),
        talkative_current=talkative_maximum,
        talkative_maximum=talkative_maximum,
        profile=_build_npc_profile(role_id, name),
    )
    role.profile.name = name
    role.profile.role_type = "npc"
    _recompute_player_derived(role.profile)
    _ensure_npc_role_complete(save, role)
    return role


_ALLOWED_TEAM_RACES = ["人类", "精灵", "矮人", "半身人", "半精灵", "侏儒", "提夫林"]
_ALLOWED_TEAM_CLASSES = ["战士", "游荡者", "牧师", "法师", "游侠", "吟游诗人", "武僧", "德鲁伊"]
_ALLOWED_TEAM_ALIGNMENTS = ["lawful_good", "neutral_good", "true_neutral", "chaotic_neutral", "lawful_neutral"]
_TEAM_BACKGROUND_OPTIONS = ["城镇守望", "行会学徒", "旅商随员", "边境猎手", "神殿侍者", "抄写员", "草药采集者", "佣兵"]
_TEAM_LANGUAGE_OPTIONS = ["通用语", "矮人语", "精灵语", "半身人语", "行商黑话"]
_TEAM_WEAPON_LIBRARY: dict[str, dict[str, object]] = {
    "长剑": {"description": "常见的制式近战武器。", "effect": "近战力量", "attack_bonus": 2, "item_type": "weapon", "aliases": ["长剑", "剑", "单手剑"]},
    "短剑": {"description": "轻巧而便于贴身使用。", "effect": "finesse dex", "attack_bonus": 2, "item_type": "weapon", "aliases": ["短剑", "匕首", "刺剑"]},
    "短弓": {"description": "适合巡猎和快速远射。", "effect": "ranged dex", "attack_bonus": 2, "item_type": "weapon", "aliases": ["短弓", "弓手", "弓"]},
    "长弓": {"description": "射程更远的远程武器。", "effect": "ranged dex", "attack_bonus": 2, "item_type": "weapon", "aliases": ["长弓"]},
    "法杖": {"description": "兼具施法与自卫用途。", "effect": "spell focus", "attack_bonus": 1, "item_type": "weapon", "aliases": ["法杖", "奥术杖"]},
    "木杖": {"description": "带着木香的施法手杖。", "effect": "spell focus", "attack_bonus": 1, "item_type": "weapon", "aliases": ["木杖", "手杖"]},
    "细剑": {"description": "便于优雅出手的轻型武器。", "effect": "finesse dex", "attack_bonus": 2, "item_type": "weapon", "aliases": ["细剑"]},
    "短棍": {"description": "练习与防身都很顺手。", "effect": "monk dex", "attack_bonus": 1, "item_type": "weapon", "aliases": ["短棍", "棍"]},
    "钉头锤": {"description": "沉稳扎实的单手武器。", "effect": "近战力量", "attack_bonus": 1, "item_type": "weapon", "aliases": ["钉头锤", "锤"]},
}
_TEAM_ARMOR_LIBRARY: dict[str, dict[str, object]] = {
    "锁子甲": {"description": "厚实可靠的金属护甲。", "armor_bonus": 4, "item_type": "armor", "aliases": ["锁子甲", "重甲"]},
    "皮甲": {"description": "轻便灵活的常用护甲。", "armor_bonus": 2, "item_type": "armor", "aliases": ["皮甲", "轻甲"]},
    "鳞甲": {"description": "兼顾防御与行动的中甲。", "armor_bonus": 3, "item_type": "armor", "aliases": ["鳞甲", "中甲"]},
    "法袍": {"description": "方便施法活动的长袍。", "armor_bonus": 0, "item_type": "armor", "aliases": ["法袍", "长袍"]},
    "练功服": {"description": "适合徒手与机动身法。", "armor_bonus": 0, "item_type": "armor", "aliases": ["练功服", "布衣"]},
}
_TEAM_ITEM_LIBRARY: dict[str, dict[str, object]] = {
    "旧地图": {"description": "边角卷起的旧地图。", "effect": "可能指向旧路线或隐藏地点", "value": 8, "aliases": ["旧地图", "地图"]},
    "草药袋": {"description": "装着干燥草药的小袋。", "effect": "常用于简单处理伤势", "value": 6, "aliases": ["草药", "草药袋", "药包"]},
    "望远镜": {"description": "折叠式小望远镜。", "effect": "适合观察远处目标", "value": 12, "aliases": ["望远镜"]},
    "记事册": {"description": "写满观察记录的小册子。", "effect": "用于记笔记和整理情报", "value": 4, "aliases": ["记事册", "笔记", "日志"]},
    "乐器": {"description": "便携式乐器，常用于表演。", "effect": "有助于演奏和社交", "value": 9, "aliases": ["乐器", "鲁特琴", "琴"]},
    "治疗药剂": {"description": "一次性恢复药剂。", "effect": "回复少量生命值", "value": 20, "uses_max": 1, "uses_left": 1, "aliases": ["药剂", "治疗药剂", "药水"]},
    "火把": {"description": "常见的照明工具。", "effect": "照明", "value": 1, "aliases": ["火把"]},
    "绳索": {"description": "结实耐用的冒险绳索。", "effect": "攀爬与固定", "value": 3, "aliases": ["绳", "绳索"]},
    "水袋": {"description": "装着清水的皮质水袋。", "effect": "补给", "value": 2, "aliases": ["水袋", "水壶"]},
}


def _limit_text(value: object, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _normalize_text_list(values: object, *, limit: int, item_limit: int = 24) -> list[str]:
    raw_values = values if isinstance(values, list) else []
    items: list[str] = []
    for value in raw_values:
        text = _limit_text(value, item_limit)
        if not text or text in items:
            continue
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _merge_unique(first: list[str], second: list[str], limit: int) -> list[str]:
    merged: list[str] = []
    for value in [*first, *second]:
        text = _limit_text(value, 24)
        if not text or text in merged:
            continue
        merged.append(text)
        if len(merged) >= limit:
            break
    return merged


def _match_keyword(value: str, options: Iterable[str]) -> str:
    text = _limit_text(value, 40)
    if not text:
        return ""
    lowered = text.lower()
    for option in options:
        if option.lower() in lowered:
            return option
    return ""


def _match_catalog_key(value: str, catalog: dict[str, dict[str, object]]) -> str:
    text = _limit_text(value, 40)
    if not text:
        return ""
    lowered = text.lower()
    for key, meta in catalog.items():
        aliases = [key, *[str(alias) for alias in meta.get("aliases", [])]]
        if any(alias.lower() in lowered for alias in aliases):
            return key
    return ""


def _class_default_bias(char_class: str) -> str:
    return {
        "战士": "strength",
        "游荡者": "dexterity",
        "牧师": "wisdom",
        "法师": "intelligence",
        "游侠": "dexterity",
        "吟游诗人": "charisma",
        "武僧": "dexterity",
        "德鲁伊": "wisdom",
    }.get(char_class, "strength")


def _parse_prompt_likes(prompt: str) -> list[str]:
    likes = [item for item in _build_npc_likes(prompt or "team_prompt") if item]
    for option in list(_TEAM_ITEM_LIBRARY.keys()) + ["热茶", "地方传闻", "罕见草药", "旧地图", "可靠的同伴", "安静的夜晚"]:
        if option in prompt and option not in likes:
            likes.insert(0, option)
    for match in re.findall(r"(?:喜欢|偏爱|爱好|热爱)([^，。；、]{1,12})", prompt):
        text = _limit_text(match, 12)
        if text and text not in likes:
            likes.insert(0, text)
    return likes[:5]


def _parse_prompt_languages(prompt: str) -> list[str]:
    return [lang for lang in _TEAM_LANGUAGE_OPTIONS if lang != "通用语" and lang in prompt][:2]


def _parse_prompt_inventory(prompt: str) -> list[str]:
    items: list[str] = []
    for key in _TEAM_ITEM_LIBRARY:
        if key in prompt and key not in items:
            items.append(key)
    return items[:4]


def _compose_fallback_team_background(
    *,
    source: str,
    zone_name: str,
    sub_name: str,
    race: str,
    char_class: str,
    personality: str,
    cognition: str,
    likes: list[str],
    prompt_text: str,
) -> str:
    identity = "".join(part for part in [race, char_class] if part) or "冒险者"
    source_label = "调试" if source == "debug" else source
    parts = [f"这名{identity}是通过{source_label}入口加入旅程的同行者，最近一直在【{zone_name}/{sub_name}】附近与你并肩行动。"]
    tone_parts = [part for part in [personality, cognition] if part][:2]
    if tone_parts:
        parts.append(f"第一眼看上去，他/她给人的感觉偏向{'、'.join(tone_parts)}，做决定时不会轻易放松警惕。")
    if likes:
        parts.append(f"平时会对{'、'.join(likes[:2])}这类线索格外上心，也因此更容易被相关话题打动。")
    elif prompt_text:
        parts.append(f"从你的描述来看，他/她身上最鲜明的特征与“{_limit_text(prompt_text, 24)}”有关。")
    return _limit_text("".join(parts), 280)


def _fallback_team_role_spec(save, prompt: str, source: str) -> dict[str, Any]:
    zone_name, sub_name = _current_player_area_names(save)
    prompt_text = prompt.strip()
    prompt_seed = prompt_text or "调试队友"
    race = next((item for item in _ALLOWED_TEAM_RACES if item in prompt_text), "")
    char_class = next((item for item in _ALLOWED_TEAM_CLASSES if item in prompt_text), "")
    alignment = ""
    if _contains_any([prompt_text], ["守序", "lawful"]):
        alignment = "lawful_good" if _contains_any([prompt_text], ["善良", "good"]) else "lawful_neutral"
    elif _contains_any([prompt_text], ["混乱", "chaotic"]):
        alignment = "chaotic_neutral"
    elif _contains_any([prompt_text], ["善良", "good"]):
        alignment = "neutral_good"
    elif _contains_any([prompt_text], ["中立", "neutral"]):
        alignment = "true_neutral"
    personality = "寡言" if _contains_any([prompt_text], ["寡言", "沉默", "少话"]) else ""
    if not personality and _contains_any([prompt_text], ["健谈", "活泼", "话多"]):
        personality = "健谈"
    if not personality and _contains_any([prompt_text], ["谨慎", "小心"]):
        personality = "谨慎"
    speaking_style = ""
    if _contains_any([prompt_text], ["低声", "轻声"]):
        speaking_style = "说话低声而克制"
    elif _contains_any([prompt_text], ["直率", "直接"]):
        speaking_style = "说话简短直接"
    elif personality == "寡言":
        speaking_style = "说话简短直接"
    appearance_parts: list[str] = []
    if _contains_any([prompt_text], ["斗篷", "披风"]):
        appearance_parts.append("披着旧斗篷")
    if _contains_any([prompt_text], ["疤", "伤痕"]):
        appearance_parts.append("身上留着旧伤疤")
    if _contains_any([prompt_text], ["弓", "箭"]):
        appearance_parts.append("背着一张弓")
    if _contains_any([prompt_text], ["法杖", "木杖"]):
        appearance_parts.append("手里拄着法杖")
    appearance = "，".join(appearance_parts[:2])
    cognition = "重视同伴承诺" if _contains_any([prompt_text], ["同伴", "队友", "承诺"]) else ""
    if not cognition and _contains_any([prompt_text], ["地图", "情报", "线索"]):
        cognition = "重视知识与传闻"
    secret = "似乎隐瞒着自己真正的来历。"
    if _contains_any([prompt_text], ["旧地图", "地图"]):
        secret = "手里藏着一份不愿轻易示人的旧地图线索。"
    likes = _parse_prompt_likes(prompt_text)
    languages = _parse_prompt_languages(prompt_text)
    preferred_weapon = _match_catalog_key(prompt_text, _TEAM_WEAPON_LIBRARY)
    preferred_armor = _match_catalog_key(prompt_text, _TEAM_ARMOR_LIBRARY)
    inventory_items = _parse_prompt_inventory(prompt_text)
    ability_bias = ""
    ability_tokens = {
        "力量": "strength",
        "敏捷": "dexterity",
        "体质": "constitution",
        "智力": "intelligence",
        "感知": "wisdom",
        "魅力": "charisma",
    }
    for token, key in ability_tokens.items():
        if token in prompt_text:
            ability_bias = key
            break
    if not ability_bias and char_class:
        ability_bias = _class_default_bias(char_class)
    return {
        "display_name": f"{_limit_text(prompt_seed, 12) or '调试'}队友",
        "race": race,
        "char_class": char_class,
        "sheet_background": next((item for item in _TEAM_BACKGROUND_OPTIONS if item in prompt_text), ""),
        "alignment": alignment,
        "personality": personality,
        "speaking_style": speaking_style,
        "appearance": appearance,
        "background": f"由{source}入口生成，目前在【{zone_name}/{sub_name}】附近与你同行。",
        "cognition": cognition,
        "secret": secret,
        "likes": likes,
        "languages": languages,
        "tool_proficiencies": [],
        "skills_proficient": [],
        "features_traits": [],
        "spells": [],
        "preferred_weapon": preferred_weapon,
        "preferred_armor": preferred_armor,
        "inventory_items": inventory_items,
        "notes": _limit_text(prompt_text, 160),
        "ability_bias": ability_bias,
    }


def _sanitize_team_role_spec(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    race = _match_keyword(str(raw.get("race") or ""), _ALLOWED_TEAM_RACES) or str(fallback.get("race") or "") or "人类"
    char_class = _match_keyword(str(raw.get("char_class") or ""), _ALLOWED_TEAM_CLASSES) or str(fallback.get("char_class") or "") or "战士"
    alignment = _match_keyword(str(raw.get("alignment") or ""), _ALLOWED_TEAM_ALIGNMENTS) or str(fallback.get("alignment") or "") or "neutral_good"
    likes = _normalize_text_list(raw.get("likes"), limit=5)
    if not likes:
        likes = _normalize_text_list(fallback.get("likes"), limit=5)
    languages = _merge_unique(_normalize_text_list(raw.get("languages"), limit=2, item_limit=12), _normalize_text_list(fallback.get("languages"), limit=2, item_limit=12), 2)
    languages = _merge_unique(["通用语"], languages, 3)
    preferred_weapon = _match_catalog_key(str(raw.get("preferred_weapon") or ""), _TEAM_WEAPON_LIBRARY) or _match_catalog_key(str(fallback.get("preferred_weapon") or ""), _TEAM_WEAPON_LIBRARY)
    preferred_armor = _match_catalog_key(str(raw.get("preferred_armor") or ""), _TEAM_ARMOR_LIBRARY) or _match_catalog_key(str(fallback.get("preferred_armor") or ""), _TEAM_ARMOR_LIBRARY)
    inventory_items = []
    for value in _normalize_text_list(raw.get("inventory_items"), limit=4):
        key = _match_catalog_key(value, _TEAM_ITEM_LIBRARY)
        if key and key not in inventory_items:
            inventory_items.append(key)
    for value in _normalize_text_list(fallback.get("inventory_items"), limit=4):
        key = _match_catalog_key(value, _TEAM_ITEM_LIBRARY)
        if key and key not in inventory_items:
            inventory_items.append(key)
    inventory_items = inventory_items[:4]
    ability_bias = _limit_text(raw.get("ability_bias") or fallback.get("ability_bias"), 20).lower()
    if ability_bias not in {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}:
        ability_bias = _class_default_bias(char_class)
    return {
        "display_name": _limit_text(raw.get("display_name") or fallback.get("display_name") or "调试队友", 24),
        "race": race,
        "char_class": char_class,
        "sheet_background": _limit_text(raw.get("sheet_background") or fallback.get("sheet_background") or _TEAM_BACKGROUND_OPTIONS[0], 24),
        "alignment": alignment,
        "personality": _limit_text(raw.get("personality") or fallback.get("personality"), 24),
        "speaking_style": _limit_text(raw.get("speaking_style") or fallback.get("speaking_style"), 72),
        "appearance": _limit_text(raw.get("appearance") or fallback.get("appearance"), 96),
        "background": _limit_text(raw.get("background") or fallback.get("background"), 320),
        "cognition": _limit_text(raw.get("cognition") or fallback.get("cognition"), 96),
        "secret": _limit_text(raw.get("secret") or fallback.get("secret"), 140),
        "likes": likes,
        "languages": languages,
        "tool_proficiencies": _merge_unique(_normalize_text_list(raw.get("tool_proficiencies"), limit=4), _normalize_text_list(fallback.get("tool_proficiencies"), limit=4), 4),
        "skills_proficient": _merge_unique(_normalize_text_list(raw.get("skills_proficient"), limit=5), _normalize_text_list(fallback.get("skills_proficient"), limit=5), 5),
        "features_traits": _merge_unique(_normalize_text_list(raw.get("features_traits"), limit=6), _normalize_text_list(fallback.get("features_traits"), limit=6), 6),
        "spells": _merge_unique(_normalize_text_list(raw.get("spells"), limit=5), _normalize_text_list(fallback.get("spells"), limit=5), 5),
        "preferred_weapon": preferred_weapon,
        "preferred_armor": preferred_armor,
        "inventory_items": inventory_items,
        "notes": _limit_text(raw.get("notes") or fallback.get("notes"), 280),
        "ability_bias": ability_bias,
    }


def _ai_team_role_spec(save, prompt: str, config, source: str) -> dict[str, Any] | None:
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    zone_name, sub_name = _current_player_area_names(save)
    prompt_text = (
        "You generate one teammate concept for a fantasy RPG. Return JSON only.\n"
        "Use this exact schema keys only: "
        "{\"display_name\":\"\",\"race\":\"\",\"char_class\":\"\",\"sheet_background\":\"\",\"alignment\":\"\","
        "\"personality\":\"\",\"speaking_style\":\"\",\"appearance\":\"\",\"background\":\"\",\"cognition\":\"\","
        "\"secret\":\"\",\"likes\":[],\"languages\":[],\"tool_proficiencies\":[],\"skills_proficient\":[],"
        "\"features_traits\":[],\"spells\":[],\"preferred_weapon\":\"\",\"preferred_armor\":\"\","
        "\"inventory_items\":[],\"notes\":\"\",\"ability_bias\":\"\"}.\n"
        f"Allowed race={_ALLOWED_TEAM_RACES}. Allowed char_class={_ALLOWED_TEAM_CLASSES}. "
        f"Allowed alignment={_ALLOWED_TEAM_ALIGNMENTS}. Allowed ability_bias="
        "[strength,dexterity,constitution,intelligence,wisdom,charisma].\n"
        "Keep array items short. Use Chinese strings. Do not output markdown.\n"
        "background should be 2-3 full Chinese sentences, not a fragment. cognition/secret/appearance should also be complete phrases.\n"
        f"Current area={zone_name}/{sub_name}. Source={source}. Player prompt={prompt}."
    )
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": prompt_text},
            ],
        )
        usage = getattr(resp, "usage", None)
        if usage is not None:
            token_usage_store.add(
                save.session_id,
                "chat",
                int(getattr(usage, "prompt_tokens", 0) or 0),
                int(getattr(usage, "completion_tokens", 0) or 0),
            )
        return _extract_json_content((resp.choices[0].message.content or "").strip())
    except Exception:
        return None


def _make_misc_item(role_id: str, item_key: str, index: int):
    meta = _TEAM_ITEM_LIBRARY[item_key]
    return _make_npc_item(
        f"{role_id}_misc_{index}",
        item_key,
        item_type="misc",
        description=str(meta.get("description") or ""),
        effect=str(meta.get("effect") or ""),
        value=int(meta.get("value") or 0),
    ).model_copy(
        update={
            "uses_max": meta.get("uses_max"),
            "uses_left": meta.get("uses_left"),
        }
    )


def _make_weapon_item(role_id: str, weapon_key: str):
    meta = _TEAM_WEAPON_LIBRARY[weapon_key]
    return _make_npc_item(
        f"{role_id}_weapon",
        weapon_key,
        item_type=str(meta.get("item_type") or "weapon"),
        slot_type="weapon",
        description=str(meta.get("description") or ""),
        effect=str(meta.get("effect") or ""),
        attack_bonus=int(meta.get("attack_bonus") or 0),
        value=12,
    )


def _make_armor_item(role_id: str, armor_key: str):
    meta = _TEAM_ARMOR_LIBRARY[armor_key]
    return _make_npc_item(
        f"{role_id}_armor",
        armor_key,
        item_type=str(meta.get("item_type") or "armor"),
        slot_type="armor",
        description=str(meta.get("description") or ""),
        armor_bonus=int(meta.get("armor_bonus") or 0),
        value=10,
    )


def _build_team_profile_from_spec(role_id: str, name: str, spec: dict[str, Any]) -> PlayerStaticData:
    char_class = str(spec["char_class"])
    template = _class_template(char_class)
    level = 1 + (_stable_int(f"{role_id}:lvl") % 4)
    scores = {
        "strength": _ability_score_with_seed(role_id, 1),
        "dexterity": _ability_score_with_seed(role_id, 2),
        "constitution": _ability_score_with_seed(role_id, 3),
        "intelligence": _ability_score_with_seed(role_id, 4),
        "wisdom": _ability_score_with_seed(role_id, 5),
        "charisma": _ability_score_with_seed(role_id, 6),
    }
    bias = str(spec["ability_bias"])
    scores[bias] = min(18, scores[bias] + 3)
    if bias != "constitution":
        scores["constitution"] = min(18, scores["constitution"] + 1)
    hit_dice = str(template.get("hit_dice") or "1d8")
    hit_die_size = int(hit_dice.split("d", 1)[1]) if "d" in hit_dice else 8
    con_mod = _ability_mod(scores["constitution"])
    hp_max = max(4, hit_die_size + con_mod + max(level - 1, 0) * (max(4, hit_die_size // 2 + 1) + con_mod))
    proficiency = 2 + ((level - 1) // 4)
    speed_ft = 35 if str(spec["race"]) == "半精灵" else 30
    move_speed_mph = max(3200, speed_ft * 140)
    preferred_weapon = str(spec.get("preferred_weapon") or "")
    preferred_armor = str(spec.get("preferred_armor") or "")
    default_weapon = _match_catalog_key(str(template.get("weapon", ("", "", "", 0))[0]), _TEAM_WEAPON_LIBRARY) or "长剑"
    default_armor = _match_catalog_key(str(template.get("armor", ("", "", 0))[0]), _TEAM_ARMOR_LIBRARY) or "皮甲"
    weapon_item = _make_weapon_item(role_id, preferred_weapon or default_weapon)
    armor_item = _make_armor_item(role_id, preferred_armor or default_armor)
    extra_keys: list[str] = []
    for name_or_key, item_type in template.get("extras", []):  # type: ignore[assignment]
        if str(item_type) != "misc":
            continue
        key = _match_catalog_key(str(name_or_key), _TEAM_ITEM_LIBRARY)
        if key and key not in extra_keys:
            extra_keys.append(key)
    for item_key in spec["inventory_items"]:
        if item_key not in extra_keys:
            extra_keys.append(item_key)
    extra_items = [_make_misc_item(role_id, item_key, idx) for idx, item_key in enumerate(extra_keys[:4], start=1)]
    all_items = [weapon_item, armor_item, *extra_items]
    base_languages = _pick_many(f"{role_id}:languages", [lang for lang in _TEAM_LANGUAGE_OPTIONS if lang != "通用语"], 1)
    languages = _merge_unique(spec["languages"], base_languages, 3)
    skills = _merge_unique(list(template.get("skills") or []), list(spec["skills_proficient"]), 6)
    tools = _merge_unique(list(template.get("tools") or []), list(spec["tool_proficiencies"]), 5)
    features = _merge_unique(list(template.get("features") or []), list(spec["features_traits"]), 6)
    spells = _merge_unique(list(template.get("spells") or []), list(spec["spells"]), 6)
    first_level_slots = max(int(template.get("spell_slots_level_1") or 0), 1 if spells else 0)
    profile = PlayerStaticData(
        player_id=role_id,
        name=name,
        move_speed_mph=move_speed_mph,
        role_type="npc",
        dnd5e_sheet={
            "level": level,
            "race": spec["race"],
            "char_class": char_class,
            "background": spec["sheet_background"],
            "alignment": spec["alignment"],
            "proficiency_bonus": proficiency,
            "armor_class": 10 + int(getattr(armor_item, "armor_bonus", 0)) + _ability_mod(scores["dexterity"]),
            "speed_ft": speed_ft,
            "initiative_bonus": _ability_mod(scores["dexterity"]),
            "hit_dice": hit_dice,
            "hit_points": {"current": hp_max, "maximum": hp_max, "temporary": 0},
            "ability_scores": scores,
            "saving_throws_proficient": list(template.get("saving_throws") or []),
            "skills_proficient": skills,
            "languages": languages,
            "tool_proficiencies": tools,
            "equipment": [item.name for item in all_items],
            "equipment_slots": {
                "weapon_item_id": weapon_item.item_id,
                "armor_item_id": armor_item.item_id,
            },
            "backpack": {
                "gold": 10 + (_stable_int(f"{role_id}:gold") % 25),
                "items": [item.model_dump(mode="json") for item in all_items],
            },
            "features_traits": features,
            "spells": spells,
            "spell_slots_max": {
                "level_1": first_level_slots,
                "level_2": 0,
                "level_3": 0,
                "level_4": 0,
                "level_5": 0,
                "level_6": 0,
                "level_7": 0,
                "level_8": 0,
                "level_9": 0,
            },
            "spell_slots_current": {
                "level_1": first_level_slots,
                "level_2": 0,
                "level_3": 0,
                "level_4": 0,
                "level_5": 0,
                "level_6": 0,
                "level_7": 0,
                "level_8": 0,
                "level_9": 0,
            },
            "notes": _limit_text(spec["notes"] or f"由prompt生成的队友：{spec['sheet_background']}", 160),
        },
    )
    _recompute_player_derived(profile)
    return profile


def generate_team_role_from_prompt(save, prompt: str, config=None, source: str = "debug") -> NpcRoleCard:
    zone_name, sub_name = _current_player_area_names(save)
    zone_id, sub_zone_id = _current_player_area(save)
    seed_prefix = "debug_team" if source == "debug" else "team_role"
    fallback = _fallback_team_role_spec(save, prompt, source)
    ai_spec = _ai_team_role_spec(save, prompt, config, source) or {}
    spec = _sanitize_team_role_spec(ai_spec, fallback)
    fallback_background = _compose_fallback_team_background(
        source=source,
        zone_name=zone_name,
        sub_name=sub_name,
        race=str(spec.get("race") or ""),
        char_class=str(spec.get("char_class") or ""),
        personality=str(spec.get("personality") or ""),
        cognition=str(spec.get("cognition") or ""),
        likes=list(spec.get("likes") or []),
        prompt_text=prompt.strip(),
    )
    if len(str(spec.get("background") or "").strip()) < 60:
        spec["background"] = fallback_background
    role_id = _new_id(seed_prefix)
    name = spec["display_name"] or f"{_limit_text(prompt, 12) or '调试'}队友"
    flavor = _build_npc_flavor(role_id, zone_name, sub_name, spec["background"] or "与你同行。")
    personality = spec["personality"] or flavor["personality"]
    speaking_style = spec["speaking_style"] or flavor["speaking_style"]
    if not spec["appearance"]:
        spec["appearance"] = flavor["appearance"]
    if not spec["background"]:
        spec["background"] = flavor["background"]
    if not spec["cognition"]:
        spec["cognition"] = flavor["cognition"]
    if not spec["secret"]:
        spec["secret"] = flavor["secret"]
    profile = _build_team_profile_from_spec(role_id, name, spec)
    talkative_maximum = _build_npc_talkative_maximum(role_id, personality)
    if _contains_any([personality, speaking_style, prompt], ["寡言", "沉默", "少话"]):
        talkative_maximum = max(28, talkative_maximum - 10)
    if _contains_any([personality, speaking_style, prompt], ["健谈", "活泼", "话多"]):
        talkative_maximum = min(98, talkative_maximum + 10)
    role = NpcRoleCard(
        role_id=role_id,
        name=name,
        zone_id=zone_id,
        sub_zone_id=sub_zone_id,
        source_world_revision=getattr(getattr(save, "world_state", None), "world_revision", 1),
        source_map_revision=getattr(getattr(save, "world_state", None), "map_revision", 1),
        state="in_team",
        personality=personality,
        speaking_style=speaking_style,
        appearance=spec["appearance"],
        background=spec["background"],
        cognition=spec["cognition"],
        alignment=spec["alignment"] or flavor["alignment"],
        secret=spec["secret"],
        likes=spec["likes"] or _build_npc_likes(role_id),
        talkative_current=talkative_maximum,
        talkative_maximum=talkative_maximum,
        profile=profile,
    )
    role.profile.name = name
    role.profile.role_type = "npc"
    _recompute_player_derived(role.profile)
    _ensure_npc_role_complete(save, role)
    return role


def generate_debug_teammate(req: TeamDebugGenerateRequest) -> TeamMutationResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    state = ensure_team_state(save)
    role = generate_team_role_from_prompt(save, req.prompt, req.config, source="debug")
    save.role_pool.append(role)
    member = TeamMember(
        role_id=role.role_id,
        name=role.name,
        origin_zone_id=None,
        origin_sub_zone_id=None,
        affinity=85,
        trust=75,
        join_source="debug",
        join_reason="调试生成队友",
        is_debug=True,
        debug_prompt=req.prompt.strip(),
    )
    state.members.append(member)
    sync_team_members_with_player_in_save(save)
    _append_game_log(
        save,
        req.session_id,
        "team_debug_generate",
        f"调试队友 {role.name} 已生成并加入队伍。",
        {"role_id": role.role_id},
    )
    _touch_state(state)
    save_current(save)
    return TeamMutationResponse(
        session_id=req.session_id,
        team_state=state,
        member=member,
        role=role,
        accepted=True,
        chat_feedback=f"{role.name} 已作为调试队友加入队伍。",
    )


def _team_chat_deltas(player_text: str) -> tuple[int, int]:
    if _contains_any([player_text], ["威胁", "attack", "抢", "rob", "杀", "threat"]):
        return (-2, -1)
    if _contains_any([player_text], ["谢谢", "thank", "help", "protect", "合作", "一起", "照应"]):
        return (1, 1)
    return (0, 0)


def _fallback_team_chat_reply(role: NpcRoleCard, player_text: str) -> tuple[str, str]:
    silent = any(token in f"{role.personality} {role.speaking_style} {role.background}" for token in ["沉默", "寡言", "冷淡"])
    if _contains_any([player_text], ["威胁", "attack", "抢", "rob", "杀", "threat"]):
        if silent:
            return (f"{role.name} 皱起眉头，把手按在武器旁，没有接话。", "action")
        return (f"{role.name} 压低声音道：'别把局面推得太远。'", "speech")
    if _contains_any([player_text], ["谢谢", "thank", "help", "protect", "合作", "一起", "照应"]):
        if silent:
            return (f"{role.name} 轻轻点头，示意自己会跟上。", "action")
        return (f"{role.name} 点头应道：'我会看着你的侧翼。'", "speech")
    if silent:
        return (f"{role.name} 抬眼看了你一瞬，随后安静地跟在一旁。", "action")
    return (f"{role.name} 简短回应：'明白，我会跟着你的节奏。'", "speech")


def _ai_team_chat_reply(save, role: NpcRoleCard, player_text: str, config) -> tuple[str, str] | None:
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        knowledge = build_npc_knowledge_snapshot(save, role.role_id)
        world_time_text, _ = _world_time_payload(save.area_snapshot.clock)
        context = _build_npc_context(role, recent_count=10)
        zone_name, sub_name = _current_player_area_names(save)
        default_prompt = (
            "你要扮演跑团中的队友 NPC，在队伍聊天里回应玩家。"
            "只返回 JSON，不要输出额外解释。"
            "JSON schema: {\"content\":\"...\",\"response_mode\":\"speech|action\"}。"
            "要求："
            "1. content 只写 1 句短回应，最多 35 字；"
            "2. response_mode=speech 表示直接说话，action 表示只做动作反应；"
            "3. 必须保持人设一致，不能编造当前世界中不存在或该 NPC 不该知道的人物/地点；"
            "4. 若玩家话题不值得多说，可以选择 action。"
            "\nNPC信息: name=$name, personality=$personality, speaking_style=$speaking_style, appearance=$appearance, background=$background, cognition=$cognition, alignment=$alignment"
            "\n当前位置: $zone_name / $sub_name"
            "\n当前世界时间: $world_time_text"
            "\n知识边界规则:\n$knowledge_rules"
            "\n最近对话:\n$context"
            "\n玩家刚刚在队伍里说: $player_text"
        )
        prompt = prompt_table.render(
            PromptKeys.TEAM_CHAT_USER,
            default_prompt,
            name=role.name,
            roleplay_brief=_build_npc_roleplay_brief(role),
            personality=role.personality,
            speaking_style=role.speaking_style,
            appearance=role.appearance,
            background=role.background,
            cognition=role.cognition,
            alignment=role.alignment,
            zone_name=zone_name,
            sub_name=sub_name,
            world_time_text=world_time_text,
            knowledge_rules="\n".join(f"- {item}" for item in knowledge.response_rules),
            context=context,
            player_text=player_text,
        )
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": config.gm_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        usage = resp.usage
        token_usage_store.add(
            save.session_id,
            "chat",
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )
        parsed = json.loads((resp.choices[0].message.content or "{}").strip())
        content = str(parsed.get("content") or "").strip()
        if not content:
            return None
        response_mode = str(parsed.get("response_mode") or "speech").strip().lower()
        if response_mode not in {"speech", "action"}:
            response_mode = "speech"
        return content[:120], response_mode
    except Exception:
        return None


def team_chat(req: TeamChatRequest) -> TeamChatResponse:
    time_spent_min = apply_speech_time(req.session_id, req.player_message, req.config)
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        save.session_id = req.session_id
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()
    state = ensure_team_state(save)
    sync_team_members_with_player_in_save(save)
    player_text = req.player_message.strip()
    if not state.members:
        return TeamChatResponse(
            session_id=req.session_id,
            player_message=player_text,
            replies=[],
            team_state=state,
            time_spent_min=time_spent_min,
        )

    replies: list[TeamChatReply] = []
    leave_ids: list[str] = []
    for member in list(state.members):
        role = next((item for item in save.role_pool if item.role_id == member.role_id), None)
        if role is None:
            continue
        _append_npc_dialogue(
            role=role,
            speaker="player",
            speaker_role_id=save.player_static_data.player_id,
            speaker_name=save.player_static_data.name,
            content=player_text,
            clock=save.area_snapshot.clock,
            context_kind="team_chat",
        )
        generated = _ai_team_chat_reply(save, role, player_text, req.config)
        if generated is None:
            content, response_mode = _fallback_team_chat_reply(role, player_text)
        else:
            content, response_mode = generated
        affinity_delta, trust_delta = _team_chat_deltas(player_text)
        _append_npc_dialogue(
            role=role,
            speaker="npc",
            speaker_role_id=role.role_id,
            speaker_name=role.name,
            content=content,
            clock=save.area_snapshot.clock,
            context_kind="team_chat",
        )
        member.affinity = _clamp_score(member.affinity + affinity_delta)
        member.trust = _clamp_score(member.trust + trust_delta)
        member.last_reaction_at = _utc_now()
        member.last_reaction_preview = content[:120]
        role.attitude_changes.append(f"{member.last_reaction_at} team_chat:{affinity_delta}/{trust_delta}")
        role.attitude_changes = role.attitude_changes[-50:]
        role.cognition_changes.append(f"{member.last_reaction_at} 队伍聊天: {player_text[:48]}")
        role.cognition_changes = role.cognition_changes[-50:]
        reaction = TeamReaction(
            reaction_id=_new_id("treact"),
            member_role_id=member.role_id,
            member_name=member.name,
            trigger_kind="team_chat",
            content=content,
            affinity_delta=affinity_delta,
            trust_delta=trust_delta,
        )
        state.reactions.append(reaction)
        state.reactions = state.reactions[-100:]
        _append_game_log(
            save,
            req.session_id,
            "team_chat",
            f"{member.name}: {content}",
            {
                "role_id": member.role_id,
                "response_mode": response_mode,
                "affinity_delta": affinity_delta,
                "trust_delta": trust_delta,
            },
        )
        replies.append(
            TeamChatReply(
                member_role_id=member.role_id,
                member_name=member.name,
                content=content,
                response_mode=response_mode,  # type: ignore[arg-type]
                affinity_delta=affinity_delta,
                trust_delta=trust_delta,
            )
        )
        if member.affinity <= 0:
            leave_ids.append(member.role_id)

    for role_id in leave_ids:
        member = _find_member(state, role_id)
        if member is None:
            continue
        _remove_member_from_team_in_save(save, member, "affinity_depleted")
    if replies or leave_ids:
        _touch_state(state)
    try:
        from app.services.encounter_service import advance_active_encounter_in_save

        advance_active_encounter_in_save(save, session_id=req.session_id, minutes_elapsed=time_spent_min, config=req.config)
    except Exception:
        pass
    save_current(save)
    return TeamChatResponse(
        session_id=req.session_id,
        player_message=player_text,
        replies=replies,
        team_state=state,
        time_spent_min=time_spent_min,
    )


def _clamp_score(value: int) -> int:
    return max(0, min(100, value))


def _contains_any(texts: Iterable[str], tokens: Iterable[str]) -> bool:
    merged = " ".join(texts).lower()
    return any(token in merged for token in tokens)


def _build_reaction(role: NpcRoleCard, trigger_kind: str, player_text: str, summary: str) -> tuple[str, int, int]:
    if trigger_kind in {"zone_move", "sub_zone_move"}:
        return (f"{role.name} 调整步伐跟上你，顺手确认周围动静。", 0, 0)
    if trigger_kind == "npc_chat":
        if _contains_any([player_text], ["谢谢", "help", "cooperate", "合作", "帮"]):
            return (f"{role.name} 在一旁听着，神色明显放松了些。", 1, 1)
        return (f"{role.name} 安静旁听，没有贸然插话。", 0, 0)
    if trigger_kind == "action_check":
        if _contains_any([summary], ["失败", "critical_failure", "大失败"]):
            return (f"{role.name} 皱了皱眉，显然对这次冒险结果有些担心。", -1, -1)
        return (f"{role.name} 看起来对你的执行力多了几分认可。", 1, 1)
    if _contains_any([player_text, summary], ["威胁", "attack", "抢", "杀", "threat", "rob"]):
        return (f"{role.name} 对你的做法显得不太认同。", -2, -1)
    if _contains_any([player_text, summary], ["谢谢", "protect", "help", "合作", "照顾", "一起"]):
        return (f"{role.name} 点了点头，似乎更愿意继续跟着你。", 1, 1)
    return (f"{role.name} 记下了这件事，但暂时没有多说什么。", 0, 0)

def _ai_team_public_reply(save, role: NpcRoleCard, player_text: str, scene_summary: str, scene_context, config) -> tuple[str, str, int, int] | None:
    if config is None:
        return None
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        return None
    try:
        client = create_sync_client(config, client_cls=OpenAI)
        zone_name, sub_name = _current_player_area_names(save)
        prompt = prompt_table.render(
            PromptKeys.TEAM_PUBLIC_REACTION_USER,
            "你要扮演公开区域中的一名队友，只输出 JSON。",
            roleplay_brief=_build_npc_roleplay_brief(role),
            scene_summary=scene_summary or "公开区域中的即时互动",
            player_text=player_text,
            gm_summary=scene_summary,
            area_text=f"{zone_name} / {sub_name}",
            context=_build_npc_prompt_context(role, save.area_snapshot.clock, recent_count=8, save=save),
            scene_context_json=json.dumps(scene_context or {}, ensure_ascii=False),
        )
        resp = client.chat.completions.create(
            model=model,
            **build_completion_options(config),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": config.gm_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        usage = resp.usage
        token_usage_store.add(
            save.session_id,
            "chat",
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )
        parsed = json.loads((resp.choices[0].message.content or "{}").strip())
        action_reaction = str(parsed.get("action_reaction") or "").strip()
        speech_reply = str(parsed.get("speech_reply") or "").strip()
        content = _compose_npc_reply(action_reaction, speech_reply).strip()
        if not content:
            return None
        response_mode = "speech" if speech_reply else "action"
        affinity_delta = max(-3, min(3, int(parsed.get("affinity_delta") or 0)))
        trust_delta = max(-3, min(3, int(parsed.get("trust_delta") or 0)))
        return content[:120], response_mode, affinity_delta, trust_delta
    except Exception:
        return None


def generate_team_public_replies_in_save(
    save,
    *,
    session_id: str,
    player_text: str,
    scene_summary: str,
    scene_context=None,
    config=None,
    exclude_role_ids: set[str] | None = None,
    max_replies: int = 2,
) -> list[TeamReaction]:
    state = ensure_team_state(save)
    if not state.members:
        return []
    sync_team_members_with_player_in_save(save)
    excluded = exclude_role_ids or set()
    created: list[TeamReaction] = []
    for member in list(state.members):
        if member.role_id in excluded:
            continue
        if len(created) >= max(0, max_replies):
            break
        role = next((item for item in save.role_pool if item.role_id == member.role_id), None)
        if role is None:
            continue
        generated = _ai_team_public_reply(save, role, player_text, scene_summary, scene_context, config)
        if generated is None:
            content = f"{role.name} 先侧过脸看了看四周，手指在衣摆边轻轻收紧，暂时没有抢着出声。"
            response_mode = "action"
            affinity_delta = 0
            trust_delta = 0
        else:
            content, response_mode, affinity_delta, trust_delta = generated
        member.affinity = _clamp_score(member.affinity + affinity_delta)
        member.trust = _clamp_score(member.trust + trust_delta)
        member.last_reaction_at = _utc_now()
        member.last_reaction_preview = content[:120]
        role.attitude_changes.append(f"{member.last_reaction_at} team:public_chat:{affinity_delta}/{trust_delta}")
        role.attitude_changes = role.attitude_changes[-50:]
        reaction = TeamReaction(
            reaction_id=_new_id("treact"),
            member_role_id=member.role_id,
            member_name=member.name,
            trigger_kind="public_chat",
            content=content,
            affinity_delta=affinity_delta,
            trust_delta=trust_delta,
        )
        state.reactions.append(reaction)
        state.reactions = state.reactions[-100:]
        created.append(reaction)
        _append_npc_dialogue(
            role=role,
            speaker="npc",
            speaker_role_id=role.role_id,
            speaker_name=role.name,
            content=content,
            clock=save.area_snapshot.clock,
            context_kind="team_chat",
        )
        _append_game_log(
            save,
            session_id,
            "team_public_reaction",
            f"{member.name}: {content}",
            {"role_id": member.role_id, "response_mode": response_mode},
        )
    if created:
        _touch_state(state)
    return created


def apply_team_reactions_in_save(
    save,
    *,
    session_id: str,
    trigger_kind: str,
    player_text: str = "",
    summary: str = "",
    exclude_role_ids: set[str] | None = None,
) -> list[TeamReaction]:
    state = ensure_team_state(save)
    if not state.members:
        return []
    sync_team_members_with_player_in_save(save)
    excluded = exclude_role_ids or set()
    created: list[TeamReaction] = []
    leave_ids: list[str] = []
    for member in list(state.members):
        if member.role_id in excluded:
            continue
        role = next((item for item in save.role_pool if item.role_id == member.role_id), None)
        if role is None:
            continue
        content, affinity_delta, trust_delta = _build_reaction(role, trigger_kind, player_text, summary)
        member.affinity = _clamp_score(member.affinity + affinity_delta)
        member.trust = _clamp_score(member.trust + trust_delta)
        member.last_reaction_at = _utc_now()
        member.last_reaction_preview = content[:120]
        role.attitude_changes.append(f"{member.last_reaction_at} team:{trigger_kind}:{affinity_delta}/{trust_delta}")
        role.attitude_changes = role.attitude_changes[-50:]
        reaction = TeamReaction(
            reaction_id=_new_id("treact"),
            member_role_id=member.role_id,
            member_name=member.name,
            trigger_kind=trigger_kind,  # type: ignore[arg-type]
            content=content,
            affinity_delta=affinity_delta,
            trust_delta=trust_delta,
        )
        state.reactions.append(reaction)
        state.reactions = state.reactions[-100:]
        created.append(reaction)
        _append_game_log(
            save,
            session_id,
            "team_reaction",
            f"{member.name}: {content}",
            {
                "role_id": member.role_id,
                "trigger_kind": trigger_kind,
                "affinity_delta": affinity_delta,
                "trust_delta": trust_delta,
            },
        )
        if member.affinity <= 0:
            leave_ids.append(member.role_id)
    for role_id in leave_ids:
        member = _find_member(state, role_id)
        if member is None:
            continue
        _remove_member_from_team_in_save(save, member, "affinity_depleted")
    if created or leave_ids:
        _touch_state(state)
    return created


def apply_team_reactions(
    session_id: str,
    *,
    trigger_kind: str,
    player_text: str = "",
    summary: str = "",
    exclude_role_ids: set[str] | None = None,
) -> TeamStateResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    apply_team_reactions_in_save(
        save,
        session_id=session_id,
        trigger_kind=trigger_kind,
        player_text=player_text,
        summary=summary,
        exclude_role_ids=exclude_role_ids,
    )
    save_current(save)
    state = ensure_team_state(save)
    return TeamStateResponse(session_id=session_id, team_state=state, members=state.members)
