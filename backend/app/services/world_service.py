from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from math import ceil, sqrt
import random

from openai import OpenAI

from app.core.storage import read_save_payload, storage_state, write_save_payload
from app.core.token_usage import token_usage_store
from app.models.schemas import (
    ActionCheckRequest,
    ActionCheckResponse,
    AreaCurrentResponse,
    AreaDiscoverInteractionsRequest,
    AreaDiscoverInteractionsResponse,
    AreaExecuteInteractionRequest,
    AreaExecuteInteractionResponse,
    AreaInteraction,
    AreaMovePoint,
    AreaMoveResult,
    AreaMoveSubZoneRequest,
    AreaNpc,
    AreaSnapshot,
    AreaSubZone,
    AreaZone,
    BehaviorDescribeResponse,
    ChatConfig,
    Coord3D,
    GameLogAddRequest,
    GameLogEntry,
    GameLogListResponse,
    GameLogSettings,
    GameLogSettingsResponse,
    MapSnapshot,
    MoveRequest,
    MoveResponse,
    MovementLog,
    NpcRoleCard,
    NpcDialogueEntry,
    NpcChatRequest,
    NpcChatResponse,
    NpcGreetRequest,
    NpcGreetResponse,
    PlayerRuntimeData,
    PlayerStaticData,
    Position,
    RegionGenerateRequest,
    RegionGenerateResponse,
    RolePoolListResponse,
    RoleRelation,
    RenderMapRequest,
    RenderCircle,
    RenderMapResponse,
    RenderNode,
    RenderSubNode,
    SaveFile,
    WorldClock,
    WorldClockInitRequest,
    WorldClockInitResponse,
    Zone,
    ZoneSubZoneSeed,
)


class AIRegionGenerationError(RuntimeError):
    pass


class AIBehaviorError(RuntimeError):
    pass


_ACTION_PENALTY_RULES: dict[str, str] = {
    "attack": "hit_points.current",
    "check": "hit_points.current",
    "item_use": "hit_points.current",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_static() -> PlayerStaticData:
    return PlayerStaticData()


def _default_runtime(session_id: str) -> PlayerRuntimeData:
    return PlayerRuntimeData(
        session_id=session_id,
        current_position=Position(x=0, y=0, z=0, zone_id="zone_0_0_0"),
        updated_at=_utc_now(),
    )


def _empty_save(session_id: str) -> SaveFile:
    return SaveFile(
        session_id=session_id,
        map_snapshot=MapSnapshot(),
        player_static_data=_default_static(),
        player_runtime_data=_default_runtime(session_id),
        updated_at=_utc_now(),
    )


def _new_game_log(session_id: str, kind: str, message: str, payload: dict[str, str | int | float | bool] | None = None) -> GameLogEntry:
    return GameLogEntry(
        id=f"glog_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        session_id=session_id,
        kind=kind,
        message=message,
        payload=payload or {},
    )


def _stable_int(seed: str) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _ability_score_with_seed(seed: str, offset: int) -> int:
    base = 8 + ((_stable_int(f"{seed}:{offset}") % 11))
    return max(8, min(18, base))


def _ability_mod(score: int) -> int:
    return int((score - 10) // 2)


def _pick(seed: str, options: list[str]) -> str:
    if not options:
        return ""
    return options[_stable_int(seed) % len(options)]


def _build_npc_flavor(npc_id: str, zone_name: str, sub_name: str, sub_desc: str) -> dict[str, str]:
    personality = _pick(
        f"{npc_id}:personality",
        ["谨慎", "豪爽", "机敏", "稳重", "多疑", "热心", "冷静", "直率"],
    )
    speaking_style = _pick(
        f"{npc_id}:speech",
        ["语速平缓，措辞克制", "说话简短直接", "喜欢举例说明", "习惯先试探再表态", "带有地方口音"],
    )
    appearance = _pick(
        f"{npc_id}:appearance",
        ["披着旧斗篷", "佩戴铜制护符", "手上有旧伤疤", "衣着整洁但朴素", "背着工具包"],
    )
    cognition = _pick(
        f"{npc_id}:cognition",
        ["重视秩序", "重视利益交换", "重视同伴承诺", "重视知识与传闻", "重视安全边界"],
    )
    alignment = _pick(
        f"{npc_id}:alignment",
        ["lawful_good", "neutral_good", "true_neutral", "chaotic_neutral", "lawful_neutral"],
    )
    background = f"常驻于【{zone_name}/{sub_name}】。{sub_desc[:42]}".strip()
    return {
        "personality": personality,
        "speaking_style": speaking_style,
        "appearance": appearance,
        "background": background,
        "cognition": cognition,
        "alignment": alignment,
    }


def _build_npc_identity(zone_name: str, sub_name: str, sub_id: str, idx: int = 0) -> tuple[str, str]:
    base_seed = f"{sub_id}:{idx}"
    title = _pick(base_seed + ":title", ["哨卫", "商贩", "学徒", "向导", "巡逻者", "抄写员", "药师", "工匠"])
    surname = _pick(base_seed + ":surname", ["林", "岳", "岚", "霁", "川", "墨", "澜", "宁", "祁", "商"])
    given = _pick(base_seed + ":given", ["安", "洛", "越", "岑", "遥", "珂", "骁", "弈", "乔", "白"])
    role_id = f"npc_{sub_id}_{(_stable_int(base_seed) % 9999):04d}"
    name = f"{zone_name}{title}{surname}{given}"
    return role_id, name


def _build_npc_profile(npc_id: str, npc_name: str) -> PlayerStaticData:
    strength = _ability_score_with_seed(npc_id, 1)
    dexterity = _ability_score_with_seed(npc_id, 2)
    constitution = _ability_score_with_seed(npc_id, 3)
    intelligence = _ability_score_with_seed(npc_id, 4)
    wisdom = _ability_score_with_seed(npc_id, 5)
    charisma = _ability_score_with_seed(npc_id, 6)
    level = 1 + (_stable_int(f"{npc_id}:lvl") % 5)
    con_mod = _ability_mod(constitution)
    hp_max = max(4, 8 + con_mod + max(level - 1, 0) * (5 + con_mod))
    proficiency = 2 + ((level - 1) // 4)
    armor_class = 10 + _ability_mod(dexterity)
    speed_ft = 30
    initiative_bonus = _ability_mod(dexterity)

    return PlayerStaticData(
        player_id=npc_id,
        name=npc_name,
        move_speed_mph=4200,
        role_type="npc",
        dnd5e_sheet={
            "level": level,
            "race": "",
            "char_class": "",
            "background": "",
            "alignment": "",
            "proficiency_bonus": proficiency,
            "armor_class": armor_class,
            "speed_ft": speed_ft,
            "initiative_bonus": initiative_bonus,
            "hit_dice": "1d8",
            "hit_points": {"current": hp_max, "maximum": hp_max, "temporary": 0},
            "ability_scores": {
                "strength": strength,
                "dexterity": dexterity,
                "constitution": constitution,
                "intelligence": intelligence,
                "wisdom": wisdom,
                "charisma": charisma,
            },
            "saving_throws_proficient": [],
            "skills_proficient": [],
            "languages": [],
            "tool_proficiencies": [],
            "equipment": [],
            "features_traits": [],
            "spells": [],
            "notes": "",
        },
    )


def _ensure_role_pool_from_area(save: SaveFile) -> bool:
    changed = False
    role_map = {r.role_id: r for r in save.role_pool}

    for sub in save.area_snapshot.sub_zones:
        if not sub.npcs:
            zone_name = next((z.name for z in save.area_snapshot.zones if z.zone_id == sub.zone_id), sub.zone_id)
            npc_id, npc_name = _build_npc_identity(zone_name, sub.name, sub.sub_zone_id, 0)
            sub.npcs.append(AreaNpc(npc_id=npc_id, name=npc_name, state="idle"))
            changed = True

        for npc in sub.npcs:
            role = role_map.get(npc.npc_id)
            if role is None:
                zone_name = next((z.name for z in save.area_snapshot.zones if z.zone_id == sub.zone_id), sub.zone_id)
                flavor = _build_npc_flavor(npc.npc_id, zone_name, sub.name, sub.description)
                role = NpcRoleCard(
                    role_id=npc.npc_id,
                    name=npc.name,
                    zone_id=sub.zone_id,
                    sub_zone_id=sub.sub_zone_id,
                    state=npc.state or "idle",
                    personality=flavor["personality"],
                    speaking_style=flavor["speaking_style"],
                    appearance=flavor["appearance"],
                    background=flavor["background"],
                    cognition=flavor["cognition"],
                    alignment=flavor["alignment"],
                    profile=_build_npc_profile(npc.npc_id, npc.name),
                    relations=[],
                )
                save.role_pool.append(role)
                role_map[role.role_id] = role
                changed = True
            else:
                if role.name != npc.name:
                    role.name = npc.name
                    changed = True
                if role.zone_id != sub.zone_id:
                    role.zone_id = sub.zone_id
                    changed = True
                if role.sub_zone_id != sub.sub_zone_id:
                    role.sub_zone_id = sub.sub_zone_id
                    changed = True
                if role.state != (npc.state or "idle"):
                    role.state = npc.state or "idle"
                    changed = True

    role_ids = [r.role_id for r in save.role_pool]
    for idx, role in enumerate(save.role_pool):
        if role.relations:
            continue
        if len(role_ids) <= 1:
            continue
        first_target = role_ids[(idx + 1) % len(role_ids)]
        if first_target == role.role_id:
            continue
        relations = [RoleRelation(target_role_id=first_target, relation_tag="acquaintance", note="初始关联")]
        if len(role_ids) > 2 and idx % 2 == 0:
            second_target = role_ids[(idx + 2) % len(role_ids)]
            if second_target != role.role_id and second_target != first_target:
                relations.append(RoleRelation(target_role_id=second_target, relation_tag="ally", note="初始关联"))
        role.relations = relations[:2]
        changed = True

    # Remove relations pointing to the player; player relation is created only after interaction.
    player_id = save.player_static_data.player_id
    for role in save.role_pool:
        before = len(role.relations)
        role.relations = [r for r in role.relations if r.target_role_id != player_id]
        if len(role.relations) != before:
            changed = True

    return changed


def get_current_save(default_session_id: str = "sess_default") -> SaveFile:
    payload = read_save_payload(storage_state.save_path)
    if payload is None:
        save = _empty_save(default_session_id)
        save_current(save)
        return save

    save = SaveFile.model_validate(payload)
    if not save.player_runtime_data.session_id:
        save.player_runtime_data.session_id = save.session_id
    return save


def save_current(save: SaveFile) -> None:
    save.updated_at = _utc_now()
    save.player_runtime_data.updated_at = save.updated_at
    write_save_payload(storage_state.save_path, save.model_dump(mode="json"))


def clear_current_save(session_id: str) -> SaveFile:
    save = _empty_save(session_id)
    save_current(save)
    return save


def import_save(save: SaveFile) -> SaveFile:
    save_current(save)
    return save


def get_player_static(session_id: str) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    return save.player_static_data


def set_player_static(session_id: str, payload: PlayerStaticData) -> PlayerStaticData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    save.player_static_data = payload
    save_current(save)
    return save.player_static_data


def get_player_runtime(session_id: str) -> PlayerRuntimeData:
    save = get_current_save(default_session_id=session_id)
    if save.player_runtime_data.session_id != session_id:
        save.player_runtime_data.session_id = session_id
        save_current(save)
    return save.player_runtime_data


def set_player_runtime(session_id: str, payload: PlayerRuntimeData) -> PlayerRuntimeData:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    payload.session_id = session_id
    payload.updated_at = _utc_now()
    save.player_runtime_data = payload
    save_current(save)
    return save.player_runtime_data


def add_game_log(req: GameLogAddRequest) -> GameLogEntry:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    entry = _new_game_log(req.session_id, req.kind, req.message, req.payload)
    save.game_logs.append(entry)
    save_current(save)
    return entry


def get_game_logs(session_id: str, limit: int | None = None) -> GameLogListResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
        save_current(save)
    safe_limit = max(1, min(limit if limit is not None else save.game_log_settings.ai_fetch_limit, 200))
    return GameLogListResponse(session_id=session_id, items=save.game_logs[-safe_limit:])


def get_game_log_settings(session_id: str) -> GameLogSettingsResponse:
    save = get_current_save(default_session_id=session_id)
    return GameLogSettingsResponse(session_id=session_id, settings=save.game_log_settings)


def set_game_log_settings(session_id: str, settings: GameLogSettings) -> GameLogSettingsResponse:
    save = get_current_save(default_session_id=session_id)
    save.session_id = session_id
    save.game_log_settings = settings
    save_current(save)
    return GameLogSettingsResponse(session_id=session_id, settings=save.game_log_settings)


def _build_region_prompt(center: Position, count: int, world_prompt: str) -> str:
    return (
        "根据以下世界设定，生成可探索地图区块。"
        "必须返回严格 JSON，且只返回 JSON。"
        "结构如下："
        "{\"zones\":[{\"name\":\"\",\"zone_type\":\"city|village|forest|mountain|river|desert|coast|cave|ruins|unknown\",\"size\":\"small|medium|large\",\"radius_m\":120,\"x\":0,\"y\":0,\"description\":\"\",\"tags\":[\"\"],\"sub_zones\":[{\"name\":\"\",\"offset_x\":0,\"offset_y\":0,\"offset_z\":0,\"description\":\"\"}]}]}。"
        f"区块数量={count}，玩家当前位置=({center.x},{center.y},{center.z})。"
        "x,y 单位是米。为了可视化，请将坐标限制在玩家中心点半径 300 米内。"
        "至少 1 个区块与玩家当前位置相邻（可在 0-80 米内）。"
        "返回的区块名称必须是语义名称，禁止使用‘区域1/区块1’这类流水号。"
        "子区块数量规则：small=3~5, medium=5~10, large=8~15。"
        "区块半径规则：small=60~180, medium=120~300, large=240~500。"
        "区块间不能重叠：任意两区块中心距离必须大于两者 radius_m 之和。"
        "sub_zones 的 offset_* 是相对区块中心坐标偏移（单位米）。"
        f"世界设定提示：{world_prompt}"
    )


def _sub_zone_count_range(size: str) -> tuple[int, int]:
    if size == "small":
        return (3, 5)
    if size == "large":
        return (8, 15)
    return (5, 10)


def _zone_radius_range(size: str) -> tuple[int, int]:
    if size == "small":
        return (60, 180)
    if size == "large":
        return (240, 500)
    return (120, 300)


def _default_sub_zone_seeds(size: str, zone_name: str) -> list[ZoneSubZoneSeed]:
    min_count, _ = _sub_zone_count_range(size)
    rmin, rmax = _zone_radius_range(size)
    base_r = int((rmin + rmax) / 2)
    seeds: list[ZoneSubZoneSeed] = []
    for idx in range(min_count):
        angle_bucket = (idx % 6) + 1
        step = max(30, int(base_r * (0.35 + 0.1 * angle_bucket)))
        seeds.append(
            ZoneSubZoneSeed(
                name=f"{zone_name}子区{idx + 1}",
                offset_x=(step if idx % 2 == 0 else -step),
                offset_y=(step // 2 if idx % 3 == 0 else -step // 2),
                offset_z=0,
                description="自动补全的子区块",
            )
        )
    return seeds


def _fit_offset_in_radius(offset_x: int, offset_y: int, radius_m: int) -> tuple[int, int]:
    dist = sqrt(float(offset_x * offset_x + offset_y * offset_y))
    max_dist = max(1.0, float(radius_m))
    if dist <= max_dist:
        return offset_x, offset_y
    ratio = max_dist / dist
    return int(round(offset_x * ratio)), int(round(offset_y * ratio))


def _is_sub_seed_quality_bad(seeds: list[ZoneSubZoneSeed], radius_m: int) -> bool:
    if not seeds:
        return True
    center_threshold = max(8.0, float(radius_m) * 0.08)
    near_center = 0
    coords: set[tuple[int, int, int]] = set()
    for s in seeds:
        dist = sqrt(float(s.offset_x * s.offset_x + s.offset_y * s.offset_y + s.offset_z * s.offset_z))
        if dist <= center_threshold:
            near_center += 1
        coords.add((s.offset_x, s.offset_y, s.offset_z))
    if len(coords) <= 1:
        return True
    if near_center >= max(1, len(seeds) - 1):
        return True
    return False


def _enforce_non_overlap(zones: list[Zone]) -> None:
    for i in range(len(zones)):
        for j in range(i + 1, len(zones)):
            a = zones[i]
            b = zones[j]
            dx = float(b.x - a.x)
            dy = float(b.y - a.y)
            d = sqrt(dx * dx + dy * dy)
            min_d = float(a.radius_m + b.radius_m + 1)
            if d >= min_d:
                continue
            if d == 0:
                b.x += int(min_d)
                continue
            push = (min_d - d) / d
            b.x = int(round(b.x + dx * push))
            b.y = int(round(b.y + dy * push))


def _extract_json_content(content: str) -> dict:
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    return json.loads(raw)


def _build_discover_prompt(sub_zone: AreaSubZone, intent: str) -> str:
    return (
        "你是跑团场景设计器。"
        "请基于给定子区块和玩家意图，生成 1-3 个新的可交互对象。"
        "只能返回 JSON，不要输出任何额外文本。"
        "结构必须为："
        "{\"interactions\":[{\"name\":\"\",\"type\":\"item|scene|npc\",\"status\":\"ready|disabled|hidden\"}]}"
        f"。子区块名称：{sub_zone.name}。子区块描述：{sub_zone.description}。玩家意图：{intent}。"
        "要求：名称具体、可操作，不要与“观察周边”这类通用词重复。"
    )


def _coerce_interaction_type(raw: str) -> str:
    val = raw.strip().lower()
    if val in {"item", "scene", "npc"}:
        return val
    return "item"


def _coerce_interaction_status(raw: str) -> str:
    val = raw.strip().lower()
    if val in {"ready", "disabled", "hidden"}:
        return val
    return "ready"


def _validate_discovered_interactions(payload: object) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        raise AIRegionGenerationError("discover_interactions: AI 返回格式无效")
    raw_list = payload.get("interactions")
    if not isinstance(raw_list, list):
        raise AIRegionGenerationError("discover_interactions: interactions 缺失")

    result: list[dict[str, str]] = []
    for item in raw_list[:5]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        itype = _coerce_interaction_type(str(item.get("type") or "item"))
        status = _coerce_interaction_status(str(item.get("status") or "ready"))
        result.append({"name": name, "type": itype, "status": status})
    if not result:
        raise AIRegionGenerationError("discover_interactions: AI 无有效交互项")
    return result


def _ai_discover_interactions(config: ChatConfig, sub_zone: AreaSubZone, intent: str) -> list[dict[str, str]]:
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        raise AIRegionGenerationError("discover_interactions: 缺少模型配置")

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        temperature=min(max(config.temperature, 0), 2),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "你是可交互内容生成器，只输出 JSON。"},
            {"role": "user", "content": _build_discover_prompt(sub_zone, intent)},
        ],
    )
    content = (resp.choices[0].message.content or "").strip()
    if not content:
        raise AIRegionGenerationError("discover_interactions: AI 返回为空")
    parsed = _extract_json_content(content)
    return _validate_discovered_interactions(parsed)


def _ai_generate_zones(session_id: str, center: Position, count: int, world_prompt: str, config: ChatConfig) -> list[Zone]:
    if not world_prompt.strip():
        raise AIRegionGenerationError("world_prompt 不能为空")

    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        raise AIRegionGenerationError("缺少有效的模型配置或 API Key")

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            temperature=min(max(config.temperature, 0), 2),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "你是地图设计器，只输出 JSON。"},
                {"role": "user", "content": _build_region_prompt(center, count, world_prompt)},
            ],
        )
        usage = resp.usage
        token_usage_store.add(
            session_id,
            "map_generation",
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise AIRegionGenerationError("AI 返回为空")

        parsed = _extract_json_content(content)
        raw_zones = parsed.get("zones") if isinstance(parsed, dict) else None
        if not isinstance(raw_zones, list) or len(raw_zones) < count:
            raise AIRegionGenerationError("AI 返回结构缺少 zones")

        zones: list[Zone] = []
        seen_coords: set[tuple[int, int]] = set()
        for item in raw_zones[:count]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name.startswith("区域") or name.startswith("区块"):
                raise AIRegionGenerationError("AI 返回了无效区块名称")
            if "x" not in item or "y" not in item or "description" not in item:
                raise AIRegionGenerationError("AI 返回了不完整区块字段")
            x = int(item.get("x"))
            y = int(item.get("y"))
            if abs(x - center.x) > 1000 or abs(y - center.y) > 1000:
                raise AIRegionGenerationError("AI 返回了超出地图可视范围的坐标")
            description = str(item.get("description") or "").strip()
            if not description:
                raise AIRegionGenerationError("AI 返回了空区块描述")
            zone_type = str(item.get("zone_type") or "").strip().lower() or "unknown"
            if zone_type not in {"city", "village", "forest", "mountain", "river", "desert", "coast", "cave", "ruins", "unknown"}:
                zone_type = "unknown"
            size = str(item.get("size") or "").strip().lower() or "medium"
            if size not in {"small", "medium", "large"}:
                size = "medium"
            rmin, rmax = _zone_radius_range(size)
            raw_radius = int(item.get("radius_m") or int((rmin + rmax) / 2))
            radius_m = min(rmax, max(rmin, raw_radius))
            tags_raw = item.get("tags")
            tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else ["generated", "ai"]
            sub_raw = item.get("sub_zones")
            seeds: list[ZoneSubZoneSeed] = []
            if isinstance(sub_raw, list):
                for sub in sub_raw[:20]:
                    if not isinstance(sub, dict):
                        continue
                    sub_name = str(sub.get("name") or "").strip()
                    if not sub_name:
                        continue
                    seeds.append(
                        ZoneSubZoneSeed(
                            name=sub_name,
                            offset_x=int(sub.get("offset_x") or 0),
                            offset_y=int(sub.get("offset_y") or 0),
                            offset_z=int(sub.get("offset_z") or 0),
                            description=str(sub.get("description") or "").strip(),
                        )
                    )
            min_count, max_count = _sub_zone_count_range(size)
            if len(seeds) < min_count or len(seeds) > max_count:
                seeds = _default_sub_zone_seeds(size, name)
            if _is_sub_seed_quality_bad(seeds, radius_m):
                seeds = _default_sub_zone_seeds(size, name)
            normalized_seeds: list[ZoneSubZoneSeed] = []
            for s in seeds:
                ox, oy = _fit_offset_in_radius(s.offset_x, s.offset_y, radius_m)
                normalized_seeds.append(
                    ZoneSubZoneSeed(
                        name=s.name,
                        offset_x=ox,
                        offset_y=oy,
                        offset_z=s.offset_z,
                        description=s.description,
                    )
                )
            zone_id = f"zone_{x}_{y}_{center.z}"
            coord = (x, y)
            if coord in seen_coords:
                continue
            seen_coords.add(coord)
            zones.append(
                Zone(
                    zone_id=zone_id,
                    name=name,
                    x=x,
                    y=y,
                    z=center.z,
                    zone_type=zone_type,
                    size=size,
                    radius_m=radius_m,
                    description=description,
                    tags=tags,
                    sub_zones=normalized_seeds,
                )
            )

        if not zones:
            raise AIRegionGenerationError("AI 结果解析后无有效区块")
        _enforce_non_overlap(zones)
        if len(seen_coords) < min(count, 3):
            raise AIRegionGenerationError("AI 返回的区块坐标过于集中")
        return zones
    except AIRegionGenerationError:
        raise
    except Exception as exc:
        raise AIRegionGenerationError(str(exc)) from exc


def generate_regions(req: RegionGenerateRequest) -> RegionGenerateResponse:
    save = get_current_save(default_session_id=req.session_id)
    if (not req.force_regenerate) and save.session_id == req.session_id and save.map_snapshot.zones:
        _ensure_area_snapshot(save)
        save_current(save)
        return RegionGenerateResponse(session_id=req.session_id, generated=False, zones=save.map_snapshot.zones)

    count = min(req.desired_count, req.max_count, 10)
    zones = _ai_generate_zones(req.session_id, req.player_position, count, req.world_prompt, req.config)

    save.session_id = req.session_id
    save.map_snapshot.player_position = req.player_position
    save.map_snapshot.zones = zones
    save.area_snapshot = _area_snapshot_from_map(save)
    _ensure_role_pool_from_area(save)
    save.player_runtime_data.session_id = req.session_id
    save.player_runtime_data.current_position = req.player_position
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "area_generate",
            f"生成区块 {len(zones)} 个",
            {"count": len(zones), "source": "/api/v1/world-map/regions/generate"},
        )
    )
    save_current(save)

    return RegionGenerateResponse(session_id=req.session_id, generated=True, zones=zones)


def generate_zones_for_chat(session_id: str, config: ChatConfig, world_prompt: str, count: int = 1) -> list[Zone]:
    save = get_current_save(default_session_id=session_id)
    center = (
        save.player_runtime_data.current_position
        or save.map_snapshot.player_position
        or Position(x=0, y=0, z=0, zone_id="zone_0_0_0")
    )
    safe_count = max(1, min(int(count or 1), 3))
    generated = _ai_generate_zones(session_id, center, safe_count, world_prompt, config)

    existing = {z.zone_id for z in save.map_snapshot.zones}
    appended: list[Zone] = []
    for zone in generated:
        if zone.zone_id in existing:
            continue
        save.map_snapshot.zones.append(zone)
        existing.add(zone.zone_id)
        appended.append(zone)

    if save.map_snapshot.player_position is None:
        save.map_snapshot.player_position = center
    _ensure_area_snapshot(save)
    for zone in appended:
        if not any(z.zone_id == zone.zone_id for z in save.area_snapshot.zones):
            save.area_snapshot.zones.append(
                AreaZone(
                    zone_id=zone.zone_id,
                    name=zone.name,
                    zone_type=_infer_zone_type(zone.tags),
                    size="medium",
                    center=Coord3D(x=zone.x, y=zone.y, z=zone.z),
                    description=zone.description,
                    sub_zone_ids=[],
                )
            )
        _ensure_zone_subzone_placeholders(save, zone.zone_id)
    _ensure_role_pool_from_area(save)
    save.session_id = session_id
    save.player_runtime_data.session_id = session_id
    if appended:
        save.game_logs.append(
            _new_game_log(
                session_id,
                "area_generate",
                f"聊天生成区块 {len(appended)} 个",
                {"count": len(appended), "source": "tool.generate_zone"},
            )
        )
    save_current(save)
    return appended


def render_map(req: RenderMapRequest) -> RenderMapResponse:
    nodes = [RenderNode(zone_id=z.zone_id, name=z.name, x=z.x, y=z.y) for z in req.zones]
    sub_nodes: list[RenderSubNode] = []
    circles: list[RenderCircle] = []
    for z in req.zones:
        circles.append(RenderCircle(zone_id=z.zone_id, center_x=z.x, center_y=z.y, radius_m=z.radius_m))
        for idx, sub in enumerate(z.sub_zones):
            sub_nodes.append(
                RenderSubNode(
                    sub_zone_id=f"sub_{z.zone_id}_{idx + 1}",
                    zone_id=z.zone_id,
                    name=sub.name,
                    x=z.x + sub.offset_x,
                    y=z.y + sub.offset_y,
                )
            )
    xs = [n.x for n in nodes] + [s.x for s in sub_nodes] or [0]
    ys = [n.y for n in nodes] + [s.y for s in sub_nodes] or [0]
    viewport = {
        "min_x": min(xs) - 10,
        "max_x": max(xs) + 10,
        "min_y": min(ys) - 10,
        "max_y": max(ys) + 10,
    }
    return RenderMapResponse(
        session_id=req.session_id,
        viewport=viewport,
        nodes=nodes,
        sub_nodes=sub_nodes,
        circles=circles,
        player_marker={"x": req.player_position.x, "y": req.player_position.y},
    )


def _distance_m(from_zone: Zone, to_zone: Zone) -> float:
    dx = float(from_zone.x - to_zone.x)
    dy = float(from_zone.y - to_zone.y)
    return sqrt(dx * dx + dy * dy)


def move_to_zone(req: MoveRequest) -> MoveResponse:
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        raise ValueError("session mismatch with current save")

    to_zone = next((z for z in save.map_snapshot.zones if z.zone_id == req.to_zone_id), None)
    if to_zone is None:
        raise KeyError("zone not found")

    from_zone = next((z for z in save.map_snapshot.zones if z.zone_id == req.from_zone_id), None)
    if from_zone is None:
        current = save.player_runtime_data.current_position or save.map_snapshot.player_position
        if current is None:
            current = Position(x=0, y=0, z=0, zone_id=req.from_zone_id)
        from_zone = Zone(
            zone_id=current.zone_id or req.from_zone_id,
            name="当前位置",
            x=current.x,
            y=current.y,
            z=current.z,
            description="玩家当前位置",
            tags=["runtime"],
        )

    distance_m = _distance_m(from_zone, to_zone)
    speed_mph = max(1, save.player_static_data.move_speed_mph)
    duration_min = max(1, ceil((distance_m / speed_mph) * 60.0))

    new_position = Position(x=to_zone.x, y=to_zone.y, z=to_zone.z, zone_id=to_zone.zone_id)
    save.map_snapshot.player_position = new_position
    save.player_runtime_data.session_id = req.session_id
    save.player_runtime_data.current_position = new_position
    _ensure_area_snapshot(save)
    _ensure_zone_subzone_placeholders(save, to_zone.zone_id)
    save.area_snapshot.current_zone_id = to_zone.zone_id
    save.area_snapshot.current_sub_zone_id = None
    if save.area_snapshot.clock is not None:
        save.area_snapshot.clock = _advance_clock(save.area_snapshot.clock, duration_min)

    actor_name = req.player_name or save.player_static_data.name
    from_name = from_zone.name
    to_name = to_zone.name
    movement_log = MovementLog(
        id=f"log_{int(datetime.now(timezone.utc).timestamp())}",
        summary=f"{actor_name} 从【{from_name}】移动到【{to_name}】，花费了 {duration_min} 分钟",
        payload={
            "from_zone_id": req.from_zone_id,
            "from_zone_name": from_name,
            "to_zone_id": req.to_zone_id,
            "to_zone_name": to_name,
            "from_x": from_zone.x,
            "from_y": from_zone.y,
            "to_x": to_zone.x,
            "to_y": to_zone.y,
            "to_zone_description": to_zone.description,
            "distance_m": round(distance_m, 3),
            "duration_min": duration_min,
        },
    )
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "move",
            movement_log.summary,
            {
                "to_zone_id": to_zone.zone_id,
                "to_zone_name": to_zone.name,
                "duration_min": duration_min,
                "distance_m": round(distance_m, 3),
            },
        )
    )
    save_current(save)

    return MoveResponse(
        session_id=req.session_id,
        new_position=new_position,
        duration_min=duration_min,
        movement_log=movement_log,
    )


def _default_world_clock(calendar: str = "fantasy_default") -> WorldClock:
    return WorldClock(
        calendar=calendar,
        year=1024,
        month=3,
        day=14,
        hour=9,
        minute=30,
        updated_at=_utc_now(),
    )


def _clock_to_datetime(clock: WorldClock) -> datetime:
    return datetime(
        year=max(clock.year, 1),
        month=min(max(clock.month, 1), 12),
        day=min(max(clock.day, 1), 28),
        hour=min(max(clock.hour, 0), 23),
        minute=min(max(clock.minute, 0), 59),
        tzinfo=timezone.utc,
    )


def _advance_clock(clock: WorldClock | None, delta_min: int) -> WorldClock:
    base = clock or _default_world_clock()
    dt = _clock_to_datetime(base) + timedelta(minutes=max(delta_min, 0))
    return WorldClock(
        calendar=base.calendar,
        year=dt.year,
        month=dt.month,
        day=dt.day,
        hour=dt.hour,
        minute=dt.minute,
        updated_at=_utc_now(),
    )


def _distance3d_m(a: Coord3D, b: Coord3D) -> float:
    dx = float(a.x - b.x)
    dy = float(a.y - b.y)
    dz = float(a.z - b.z)
    return sqrt(dx * dx + dy * dy + dz * dz)


def _infer_zone_type(tags: list[str]) -> str:
    norm = {t.strip().lower() for t in tags}
    if {"city", "urban", "town"} & norm:
        return "city"
    if {"village", "rural"} & norm:
        return "village"
    if {"forest", "wood"} & norm:
        return "forest"
    if {"mountain"} & norm:
        return "mountain"
    if {"river"} & norm:
        return "river"
    if {"desert"} & norm:
        return "desert"
    if {"coast", "beach", "sea"} & norm:
        return "coast"
    return "unknown"


def _area_snapshot_from_map(save: SaveFile) -> AreaSnapshot:
    zones: list[AreaZone] = []
    sub_zones: list[AreaSubZone] = []
    for idx, zone in enumerate(save.map_snapshot.zones):
        sub_ids: list[str] = []
        seeds = zone.sub_zones or _default_sub_zone_seeds(zone.size, zone.name)
        for sidx, seed in enumerate(seeds):
            ox, oy = _fit_offset_in_radius(seed.offset_x, seed.offset_y, zone.radius_m)
            sub_id = f"sub_{zone.zone_id}_{sidx + 1}"
            sub_ids.append(sub_id)
            npc_id, npc_name = _build_npc_identity(zone.name, seed.name, sub_id, 0)
            sub_zones.append(
                AreaSubZone(
                    sub_zone_id=sub_id,
                    zone_id=zone.zone_id,
                    name=seed.name,
                    coord=Coord3D(x=zone.x + ox, y=zone.y + oy, z=zone.z + seed.offset_z),
                    description=seed.description or zone.description,
                    generated_mode="pre",
                    key_interactions=[
                        AreaInteraction(
                            interaction_id=f"int_{zone.zone_id}_{sidx + 1}_observe",
                            name="观察周边",
                            type="scene",
                            generated_mode="pre",
                            placeholder=True,
                        )
                    ],
                    npcs=[AreaNpc(npc_id=npc_id, name=npc_name, state="idle")],
                )
            )
        zones.append(
            AreaZone(
                zone_id=zone.zone_id,
                name=zone.name,
                zone_type=(zone.zone_type or _infer_zone_type(zone.tags)),
                size=zone.size,
                center=Coord3D(x=zone.x, y=zone.y, z=zone.z),
                radius_m=zone.radius_m,
                description=zone.description,
                sub_zone_ids=sub_ids,
            )
        )
        if idx > 40:
            break

    current_zone_id = save.player_runtime_data.current_position.zone_id if save.player_runtime_data.current_position else None
    current_sub_zone_id = None
    if not current_zone_id and zones:
        current_zone_id = zones[0].zone_id
        current_sub_zone_id = None

    return AreaSnapshot(
        zones=zones,
        sub_zones=sub_zones,
        current_zone_id=current_zone_id,
        current_sub_zone_id=current_sub_zone_id,
        clock=_default_world_clock(),
    )


def _ensure_area_snapshot(save: SaveFile) -> None:
    snap = save.area_snapshot
    if not snap.zones and save.map_snapshot.zones:
        save.area_snapshot = _area_snapshot_from_map(save)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()
    _ensure_role_pool_from_area(save)


def _ensure_zone_subzone_placeholders(save: SaveFile, zone_id: str) -> str:
    snap = save.area_snapshot
    zone = next((z for z in snap.zones if z.zone_id == zone_id), None)
    if zone is None:
        map_zone = next((z for z in save.map_snapshot.zones if z.zone_id == zone_id), None)
        zone_name = map_zone.name if map_zone else zone_id
        zone_desc = map_zone.description if map_zone else "自动生成区块"
        zone_size = map_zone.size if map_zone else "medium"
        zone_type = map_zone.zone_type if map_zone else "unknown"
        center_x = map_zone.x if map_zone else 0
        center_y = map_zone.y if map_zone else 0
        center_z = map_zone.z if map_zone else 0
        zone = AreaZone(
            zone_id=zone_id,
            name=zone_name,
            zone_type=zone_type,
            size=zone_size,
            center=Coord3D(x=center_x, y=center_y, z=center_z),
            radius_m=(map_zone.radius_m if map_zone else 120),
            description=zone_desc,
            sub_zone_ids=[],
        )
        snap.zones.append(zone)

    map_zone = next((z for z in save.map_snapshot.zones if z.zone_id == zone_id), None)
    seeds = (map_zone.sub_zones if map_zone and map_zone.sub_zones else _default_sub_zone_seeds(zone.size, zone.name))
    if _is_sub_seed_quality_bad(seeds, zone.radius_m):
        seeds = _default_sub_zone_seeds(zone.size, zone.name)
    first_sub_id = ""
    for sidx, seed in enumerate(seeds):
        sub_id = f"sub_{zone_id}_{sidx + 1}"
        if not first_sub_id:
            first_sub_id = sub_id
        sub = next((s for s in snap.sub_zones if s.sub_zone_id == sub_id), None)
        if sub is None:
            sub = AreaSubZone(
                sub_zone_id=sub_id,
                zone_id=zone_id,
                name=seed.name,
                coord=Coord3D(
                    x=zone.center.x + _fit_offset_in_radius(seed.offset_x, seed.offset_y, zone.radius_m)[0],
                    y=zone.center.y + _fit_offset_in_radius(seed.offset_x, seed.offset_y, zone.radius_m)[1],
                    z=zone.center.z + seed.offset_z,
                ),
                description=seed.description or zone.description or "默认子区块",
                generated_mode="pre",
                key_interactions=[],
                npcs=[],
            )
            snap.sub_zones.append(sub)
        if not sub.key_interactions:
            sub.key_interactions.append(
                AreaInteraction(
                    interaction_id=f"int_{zone_id}_{sidx + 1}_observe",
                    name="观察周边",
                    type="scene",
                    generated_mode="pre",
                    placeholder=True,
                )
            )
        if not sub.npcs:
            npc_id, npc_name = _build_npc_identity(zone.name, sub.name, sub_id, sidx)
            sub.npcs.append(AreaNpc(npc_id=npc_id, name=npc_name, state="idle"))
        if sub_id not in zone.sub_zone_ids:
            zone.sub_zone_ids.append(sub_id)
    return first_sub_id


def init_world_clock(req: WorldClockInitRequest) -> WorldClockInitResponse:
    save = get_current_save(default_session_id=req.session_id)
    save.session_id = req.session_id
    _ensure_area_snapshot(save)
    save.area_snapshot.clock = _default_world_clock(req.calendar)
    save_current(save)
    return WorldClockInitResponse(ok=True, clock=save.area_snapshot.clock)


def get_area_current(session_id: str) -> AreaCurrentResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    save_current(save)
    return AreaCurrentResponse(ok=True, area_snapshot=save.area_snapshot)


def get_role_pool(session_id: str, query: str | None = None, limit: int = 200) -> RolePoolListResponse:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    save_current(save)

    q = (query or "").strip().lower()
    filtered = save.role_pool
    if q:
        filtered = [r for r in save.role_pool if q in r.name.lower() or q in r.role_id.lower()]
    safe_limit = max(1, min(int(limit or 200), 500))
    items = filtered[:safe_limit]
    return RolePoolListResponse(session_id=session_id, total=len(filtered), items=items)


def get_role_card(session_id: str, role_id: str) -> NpcRoleCard:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    save_current(save)
    role = next((r for r in save.role_pool if r.role_id == role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    return role


def _rough_token_count(text: str) -> int:
    clean = text.strip()
    if not clean:
        return 1
    # Rough token estimation for mixed CJK/Latin input.
    return max(1, ceil(len(clean) / 4))


def _speech_time_minutes(text: str, config: ChatConfig | None) -> tuple[int, int]:
    token_count = _rough_token_count(text)
    unit_min = max(1, int((config.speech_time_per_50_tokens_min if config is not None else 1) or 1))
    time_spent_min = max(1, ceil((token_count / 50.0) * unit_min))
    return token_count, time_spent_min


def _world_time_payload(clock: WorldClock | None) -> tuple[str, dict[str, str | int]]:
    if clock is None:
        return "未初始化时钟", {}
    text = f"{clock.year:04d}-{clock.month:02d}-{clock.day:02d} {clock.hour:02d}:{clock.minute:02d}"
    payload: dict[str, str | int] = {
        "calendar": clock.calendar,
        "year": clock.year,
        "month": clock.month,
        "day": clock.day,
        "hour": clock.hour,
        "minute": clock.minute,
    }
    return text, payload


def _append_npc_dialogue(
    role: NpcRoleCard,
    speaker: str,
    speaker_role_id: str,
    speaker_name: str,
    content: str,
    clock: WorldClock | None,
) -> None:
    world_time_text, world_time = _world_time_payload(clock)
    role.dialogue_logs.append(
        NpcDialogueEntry(
            id=f"dlg_{int(datetime.now(timezone.utc).timestamp() * 1000)}_{len(role.dialogue_logs)}",
            speaker=("player" if speaker == "player" else "npc"),  # type: ignore[arg-type]
            speaker_role_id=speaker_role_id,
            speaker_name=speaker_name,
            content=content.strip(),
            world_time_text=world_time_text,
            world_time=world_time,
        )
    )
    # Keep role card compact: only retain the latest 200 entries.
    if len(role.dialogue_logs) > 200:
        role.dialogue_logs = role.dialogue_logs[-200:]


def _build_npc_context(role: NpcRoleCard, recent_count: int = 16) -> str:
    if not role.dialogue_logs:
        return "无历史对话。"
    lines: list[str] = []
    for item in role.dialogue_logs[-recent_count:]:
        who = "玩家" if item.speaker == "player" else role.name
        lines.append(f"[{item.world_time_text}] {who}: {item.content}")
    return "\n".join(lines)


def apply_speech_time(session_id: str, text: str, config: ChatConfig | None) -> int:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()

    token_count, time_spent_min = _speech_time_minutes(text, config)
    save.area_snapshot.clock = _advance_clock(save.area_snapshot.clock, time_spent_min)
    save.game_logs.append(
        _new_game_log(
            session_id,
            "speech_time",
            f"玩家发言消耗时间 {time_spent_min} 分钟",
            {"token_count": token_count, "time_spent_min": time_spent_min},
        )
    )
    save_current(save)
    return time_spent_min


def npc_greet(req: NpcGreetRequest) -> NpcGreetResponse:
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        save.session_id = req.session_id
    _ensure_area_snapshot(save)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()
    role = next((r for r in save.role_pool if r.role_id == req.npc_role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")

    greeting = f"{role.name} 见你走近，低声打了个招呼：'你好，第一次来这片地方吗？'"
    if req.config is not None:
        api_key = (req.config.openai_api_key or "").strip()
        model = (req.config.model or "").strip()
        if api_key and model:
            try:
                client = OpenAI(api_key=api_key)
                world_time_text, _ = _world_time_payload(save.area_snapshot.clock)
                prompt = (
                    "你是跑团NPC。场景是：玩家刚刚走到你面前，你注意到对方靠近并开口。"
                    "请生成第一反应式的自然招呼语。"
                    "要求：只输出1句口语化对话（最多35字），不要诗意描写，不要旁白，不要比喻，不要邀请长段剧情。"
                    "语气要像面对面打招呼，内容要贴合当前地点和时间。"
                    f"姓名={role.name}, 性格={role.personality}, 说话方式={role.speaking_style}, "
                    f"外观={role.appearance}, 背景={role.background}, 认知={role.cognition}, 阵营={role.alignment}, "
                    f"当前世界时间={world_time_text}"
                )
                resp = client.chat.completions.create(
                    model=model,
                    temperature=min(max(req.config.temperature, 0), 2),
                    messages=[
                        {"role": "system", "content": req.config.gm_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    greeting = content
                usage = resp.usage
                token_usage_store.add(
                    req.session_id,
                    "chat",
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                )
            except Exception:
                pass

    _append_npc_dialogue(
        role=role,
        speaker="npc",
        speaker_role_id=role.role_id,
        speaker_name=role.name,
        content=greeting,
        clock=save.area_snapshot.clock,
    )
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "npc_greet",
            f"{role.name} 向玩家问候",
            {"npc_role_id": role.role_id},
        )
    )
    save_current(save)
    return NpcGreetResponse(session_id=req.session_id, npc_role_id=role.role_id, greeting=greeting)


def npc_chat(req: NpcChatRequest) -> NpcChatResponse:
    time_spent_min = apply_speech_time(req.session_id, req.player_message, req.config)
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        save.session_id = req.session_id
    _ensure_area_snapshot(save)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()

    role = next((r for r in save.role_pool if r.role_id == req.npc_role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    player = save.player_static_data
    player_text = req.player_message.strip()
    _append_npc_dialogue(
        role=role,
        speaker="player",
        speaker_role_id=player.player_id,
        speaker_name=player.name,
        content=player_text,
        clock=save.area_snapshot.clock,
    )

    reply = f"{role.name} 点点头：'我听到了。'"
    if req.config is not None:
        api_key = (req.config.openai_api_key or "").strip()
        model = (req.config.model or "").strip()
        if api_key and model:
            try:
                client = OpenAI(api_key=api_key)
                world_time_text, _ = _world_time_payload(save.area_snapshot.clock)
                context = _build_npc_context(role)
                prompt = (
                    "你要扮演一个NPC与玩家直接对话。"
                    "必须保持人设一致，结合历史对话与当前世界时间作答。"
                    "请返回1-3句自然口语化回复，不要输出编号，不要解释规则。"
                    f"\nNPC信息: name={role.name}, personality={role.personality}, speaking_style={role.speaking_style}, "
                    f"appearance={role.appearance}, background={role.background}, cognition={role.cognition}, alignment={role.alignment}"
                    f"\n当前世界时间: {world_time_text}"
                    f"\n历史对话(按时间顺序):\n{context}"
                    f"\n玩家刚刚说: {player_text}"
                )
                resp = client.chat.completions.create(
                    model=model,
                    temperature=min(max(req.config.temperature, 0), 2),
                    messages=[
                        {"role": "system", "content": req.config.gm_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    reply = content
                usage = resp.usage
                token_usage_store.add(
                    req.session_id,
                    "chat",
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                )
            except Exception:
                pass

    _append_npc_dialogue(
        role=role,
        speaker="npc",
        speaker_role_id=role.role_id,
        speaker_name=role.name,
        content=reply,
        clock=save.area_snapshot.clock,
    )
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "npc_chat",
            f"玩家与 {role.name} 对话",
            {"npc_role_id": role.role_id, "time_spent_min": time_spent_min},
        )
    )
    save_current(save)
    return NpcChatResponse(
        session_id=req.session_id,
        npc_role_id=role.role_id,
        reply=reply,
        time_spent_min=time_spent_min,
        dialogue_logs=role.dialogue_logs[-20:],
    )


def upsert_player_relation(session_id: str, role_id: str, relation_tag: str, note: str = "") -> NpcRoleCard:
    save = get_current_save(default_session_id=session_id)
    if save.session_id != session_id:
        save.session_id = session_id
    _ensure_area_snapshot(save)
    role = next((r for r in save.role_pool if r.role_id == role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    player_id = save.player_static_data.player_id
    role.relations = [r for r in role.relations if r.target_role_id != player_id]
    role.relations.append(
        RoleRelation(
            target_role_id=player_id,
            relation_tag=(relation_tag.strip() or "met"),
            note=(note or "").strip(),
        )
    )
    save_current(save)
    return role


def _get_actor_profile(save: SaveFile, actor_role_id: str | None) -> tuple[str, PlayerStaticData]:
    if not actor_role_id or actor_role_id == save.player_static_data.player_id:
        return save.player_static_data.player_id, save.player_static_data
    role = next((r for r in save.role_pool if r.role_id == actor_role_id), None)
    if role is None:
        raise KeyError("ROLE_NOT_FOUND")
    return role.role_id, role.profile


def _ability_modifier(profile: PlayerStaticData, ability: str) -> int:
    score = getattr(profile.dnd5e_sheet.ability_scores, ability, 10)
    return int((score - 10) // 2)


def _fallback_action_plan(action_type: str, action_prompt: str) -> dict[str, int | bool | str]:
    text = action_prompt.lower()
    ability = "wisdom"
    if any(k in text for k in ["attack", "strike", "hit", "砍", "攻击"]):
        ability = "strength"
    elif any(k in text for k in ["sneak", "dodge", "stealth", "潜行", "闪避"]):
        ability = "dexterity"
    elif any(k in text for k in ["investigate", "analyze", "arcana", "调查", "推理"]):
        ability = "intelligence"
    elif any(k in text for k in ["persuade", "deceive", "intimidate", "说服", "威吓"]):
        ability = "charisma"
    requires_check = action_type in {"attack", "check"}
    return {
        "ability_used": ability,
        "dc": 12,
        "time_spent_min": 5 if action_type != "item_use" else 3,
        "requires_check": requires_check,
    }


def _ai_action_plan(req: ActionCheckRequest) -> dict[str, int | bool | str]:
    if req.config is None:
        return _fallback_action_plan(req.action_type, req.action_prompt)
    api_key = (req.config.openai_api_key or "").strip()
    model = (req.config.model or "").strip()
    if not api_key or not model:
        return _fallback_action_plan(req.action_type, req.action_prompt)

    try:
        prompt = (
            "你是跑团行动判定助手。基于玩家行动，返回JSON。"
            "字段: ability_used(strength|dexterity|constitution|intelligence|wisdom|charisma),"
            "dc(5-30),time_spent_min(>=1),requires_check(boolean)。"
            "action_type=attack/check/item_use。"
            f"action_type={req.action_type}, action_prompt={req.action_prompt}"
        )
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            temperature=min(max(req.config.temperature, 0), 2),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "你只输出JSON。"},
                {"role": "user", "content": prompt},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        parsed = _extract_json_content(content)
        ability = str(parsed.get("ability_used") or "").strip().lower()
        if ability not in {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}:
            ability = "wisdom"
        dc = int(parsed.get("dc") or 12)
        dc = max(5, min(30, dc))
        time_spent = int(parsed.get("time_spent_min") or 5)
        time_spent = max(1, min(180, time_spent))
        requires_check = bool(parsed.get("requires_check"))
        if req.action_type in {"attack", "check"}:
            requires_check = True
        return {"ability_used": ability, "dc": dc, "time_spent_min": time_spent, "requires_check": requires_check}
    except Exception:
        return _fallback_action_plan(req.action_type, req.action_prompt)


def _apply_penalty(profile: PlayerStaticData, rule_key: str, fail_gap: int) -> list[str]:
    effects: list[str] = []
    if rule_key == "hit_points.current":
        hp = profile.dnd5e_sheet.hit_points
        hp_loss = max(1, min(5, fail_gap))
        hp.current = max(0, hp.current - hp_loss)
        effects.append(f"HP -{hp_loss}")
        return effects

    if rule_key == "dnd5e_sheet.speed_ft":
        before = profile.dnd5e_sheet.speed_ft
        loss = max(1, min(5, fail_gap))
        profile.dnd5e_sheet.speed_ft = max(5, before - loss)
        effects.append(f"Speed -{loss}ft")
        return effects

    # Unknown rule keys are ignored to keep runtime stable.
    return effects


def _suggest_relation_tag(req: ActionCheckRequest, success: bool, critical: str) -> str | None:
    text = req.action_prompt.lower()
    if "npc_id=" not in text:
        return None

    if req.config is not None:
        api_key = (req.config.openai_api_key or "").strip()
        model = (req.config.model or "").strip()
        if api_key and model:
            try:
                client = OpenAI(api_key=api_key)
                prompt = (
                    "基于互动行为和结果，输出JSON: {\"relation_tag\":\"ally|friendly|neutral|wary|hostile\"}。"
                    f"action_prompt={req.action_prompt}; success={success}; critical={critical}"
                )
                resp = client.chat.completions.create(
                    model=model,
                    temperature=min(max(req.config.temperature, 0), 2),
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": "你只输出JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                )
                parsed = _extract_json_content((resp.choices[0].message.content or "").strip())
                tag = str(parsed.get("relation_tag") or "").strip().lower()
                if tag in {"ally", "friendly", "neutral", "wary", "hostile"}:
                    return tag
            except Exception:
                pass

    if critical == "critical_success":
        return "ally"
    if critical == "critical_failure":
        return "hostile"
    return "friendly" if success else "wary"


def action_check(req: ActionCheckRequest) -> ActionCheckResponse:
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        save.session_id = req.session_id
    _ensure_area_snapshot(save)
    if save.area_snapshot.clock is None:
        save.area_snapshot.clock = _default_world_clock()

    actor_role_id, profile = _get_actor_profile(save, req.actor_role_id)
    plan = _ai_action_plan(req)
    ability = str(plan["ability_used"])
    dc = int(plan["dc"])
    time_spent_min = int(plan["time_spent_min"])
    requires_check = bool(plan["requires_check"])

    dice_roll: int | None = None
    total_score: int | None = None
    critical = "none"
    success = True
    applied_effects: list[str] = []
    ability_modifier = _ability_modifier(profile, ability)

    if requires_check:
        dice_roll = random.randint(1, 20)
        total_score = dice_roll + ability_modifier
        if dice_roll == 1:
            critical = "critical_failure"
            success = False
        elif dice_roll == 20:
            critical = "critical_success"
            success = True
        else:
            success = total_score >= dc

    if not success:
        fail_gap = max(1, dc - (total_score if total_score is not None else dc))
        rule_key = _ACTION_PENALTY_RULES.get(req.action_type, "hit_points.current")
        applied_effects.extend(_apply_penalty(profile, rule_key, fail_gap))

    save.area_snapshot.clock = _advance_clock(save.area_snapshot.clock, time_spent_min)
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "action_check",
            f"行为检定: {req.action_type} | {'成功' if success else '失败'} | 耗时 {time_spent_min} 分钟",
            {
                "actor_role_id": actor_role_id,
                "action_type": req.action_type,
                "dc": dc,
                "time_spent_min": time_spent_min,
                "success": success,
            },
        )
    )
    save_current(save)

    narrative = (
        f"{profile.name} 执行了行动，耗时 {time_spent_min} 分钟。"
        f"{'检定成功。' if success else '检定失败，出现负面后果。'}"
    )
    if critical == "critical_success":
        narrative = f"{profile.name} 掷出天然20，行动大成功！耗时 {time_spent_min} 分钟。"
    elif critical == "critical_failure":
        narrative = f"{profile.name} 掷出天然1，行动大失败。耗时 {time_spent_min} 分钟。"

    relation_tag = _suggest_relation_tag(req, success, critical)

    return ActionCheckResponse(
        session_id=req.session_id,
        actor_role_id=actor_role_id,
        action_type=req.action_type,
        requires_check=requires_check,
        ability_used=ability,  # type: ignore[arg-type]
        ability_modifier=ability_modifier,
        dc=dc,
        dice_roll=dice_roll,
        total_score=total_score,
        success=success,
        critical=critical,  # type: ignore[arg-type]
        time_spent_min=time_spent_min,
        narrative=narrative,
        applied_effects=applied_effects,
        relation_tag_suggestion=relation_tag,
    )


def move_to_sub_zone(req: AreaMoveSubZoneRequest) -> AreaMoveResult:
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        raise ValueError("session mismatch with current save")
    _ensure_area_snapshot(save)
    snap = save.area_snapshot
    if snap.clock is None:
        raise ValueError("AREA_CLOCK_NOT_INIT")

    to_sub = next((s for s in snap.sub_zones if s.sub_zone_id == req.to_sub_zone_id), None)
    if to_sub is None:
        raise KeyError("AREA_SUB_ZONE_NOT_FOUND")
    if not to_sub.key_interactions:
        to_sub.key_interactions.append(
            AreaInteraction(
                interaction_id=f"int_{to_sub.zone_id}_observe",
                name="观察周边",
                type="scene",
                generated_mode="pre",
                placeholder=True,
            )
        )
    if not to_sub.npcs:
        zone_name = next((z.name for z in snap.zones if z.zone_id == to_sub.zone_id), to_sub.zone_id)
        npc_id, npc_name = _build_npc_identity(zone_name, to_sub.name, to_sub.sub_zone_id, 0)
        to_sub.npcs.append(AreaNpc(npc_id=npc_id, name=npc_name, state="idle"))
    to_coord = to_sub.coord

    from_sub = next((s for s in snap.sub_zones if s.sub_zone_id == snap.current_sub_zone_id), None)
    if from_sub is not None:
        from_point = AreaMovePoint(zone_id=from_sub.zone_id, sub_zone_id=from_sub.sub_zone_id, coord=from_sub.coord)
    else:
        from_zone = next((z for z in snap.zones if z.zone_id == (snap.current_zone_id or to_sub.zone_id)), None)
        from_center = from_zone.center if from_zone is not None else Coord3D(x=0, y=0, z=0)
        from_point = AreaMovePoint(zone_id=(from_zone.zone_id if from_zone else to_sub.zone_id), coord=from_center)

    to_point = AreaMovePoint(zone_id=to_sub.zone_id, sub_zone_id=to_sub.sub_zone_id, coord=to_coord)
    if from_point.sub_zone_id == to_point.sub_zone_id:
        return AreaMoveResult(
            ok=True,
            from_point=from_point,
            to_point=to_point,
            distance_m=0.0,
            duration_min=0,
            clock_delta_min=0,
            clock_after=snap.clock,
            movement_feedback=f"你已在【{to_sub.name}】。",
        )
    distance_m = _distance3d_m(from_point.coord, to_point.coord)
    speed_mph = max(1, save.player_static_data.move_speed_mph)
    duration_min = max(1, ceil((distance_m / speed_mph) * 60.0))
    clock_after = _advance_clock(snap.clock, duration_min)

    snap.current_zone_id = to_sub.zone_id
    snap.current_sub_zone_id = to_sub.sub_zone_id
    snap.clock = clock_after
    save.map_snapshot.player_position = Position(
        x=int(round(to_coord.x)),
        y=int(round(to_coord.y)),
        z=int(round(to_coord.z)),
        zone_id=to_sub.zone_id,
    )
    save.player_runtime_data.current_position = save.map_snapshot.player_position
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "area_move",
            f"移动到子区块【{to_sub.name}】，耗时 {duration_min} 分钟",
            {
                "to_sub_zone_id": to_sub.sub_zone_id,
                "to_zone_id": to_sub.zone_id,
                "duration_min": duration_min,
                "distance_m": round(distance_m, 3),
            },
        )
    )
    save_current(save)

    movement_feedback = f"你移动到【{to_sub.name}】，花费 {duration_min} 分钟。"
    if req.config is not None:
        try:
            api_key = (req.config.openai_api_key or "").strip()
            model = (req.config.model or "").strip()
            if api_key and model:
                client = OpenAI(api_key=api_key)
                prompt = (
                    "你是跑团GM。基于以下移动结果写一段50-120字叙事。"
                    "不要编号，不要选项。"
                    f"from={from_point.sub_zone_id or from_point.zone_id}, to={to_sub.name}, "
                    f"distance_m={round(distance_m, 2)}, duration_min={duration_min}"
                )
                resp = client.chat.completions.create(
                    model=model,
                    temperature=min(max(req.config.temperature, 0), 2),
                    messages=[
                        {"role": "system", "content": req.config.gm_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                txt = (resp.choices[0].message.content or "").strip()
                if txt:
                    movement_feedback = txt
        except Exception:
            pass

    return AreaMoveResult(
        ok=True,
        from_point=from_point,
        to_point=to_point,
        distance_m=round(distance_m, 3),
        duration_min=duration_min,
        clock_delta_min=duration_min,
        clock_after=clock_after,
        movement_feedback=movement_feedback,
    )


def discover_interactions(req: AreaDiscoverInteractionsRequest) -> AreaDiscoverInteractionsResponse:
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        raise ValueError("session mismatch with current save")
    _ensure_area_snapshot(save)
    snap = save.area_snapshot
    target = next((s for s in snap.sub_zones if s.sub_zone_id == req.sub_zone_id), None)
    if target is None:
        raise KeyError("AREA_SUB_ZONE_NOT_FOUND")

    generated_raw: list[dict[str, str]]
    if req.config is not None:
        try:
            generated_raw = _ai_discover_interactions(req.config, target, req.intent)
        except Exception:
            generated_raw = [{"name": f"调查：{req.intent[:12]}", "type": "item", "status": "ready"}]
    else:
        generated_raw = [{"name": f"调查：{req.intent[:12]}", "type": "item", "status": "ready"}]

    existing_ids = {it.interaction_id for it in target.key_interactions}
    existing_names = {it.name.strip().lower() for it in target.key_interactions}
    deduped: list[AreaInteraction] = []
    for idx, item in enumerate(generated_raw):
        name = item["name"].strip()
        name_key = name.lower()
        if not name or name_key in existing_names:
            continue
        candidate_id = f"int_{target.sub_zone_id}_{int(datetime.now(timezone.utc).timestamp())}_{idx}"
        while candidate_id in existing_ids:
            candidate_id = f"{candidate_id}_x"
        interaction = AreaInteraction(
            interaction_id=candidate_id,
            name=name,
            type=_coerce_interaction_type(item.get("type", "item")),  # pyright: ignore[reportArgumentType]
            status=_coerce_interaction_status(item.get("status", "ready")),  # pyright: ignore[reportArgumentType]
            generated_mode="instant",
            placeholder=True,
        )
        deduped.append(interaction)
        existing_ids.add(candidate_id)
        existing_names.add(name_key)
        if len(deduped) >= 3:
            break

    if not deduped:
        deduped = [
            AreaInteraction(
                interaction_id=f"int_{target.sub_zone_id}_{int(datetime.now(timezone.utc).timestamp())}",
                name=f"调查：{req.intent[:12]}",
                type="item",
                status="ready",
                generated_mode="instant",
                placeholder=True,
            )
        ]

    target.key_interactions.extend(deduped)
    if snap.clock is not None:
        snap.clock = _advance_clock(snap.clock, 1)

    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "area_refresh",
            f"在【{target.name}】发现新的可交互项",
            {
                "sub_zone_id": target.sub_zone_id,
                "count": len(deduped),
            },
        )
    )
    save_current(save)
    return AreaDiscoverInteractionsResponse(ok=True, generated_mode="instant", new_interactions=deduped)


def execute_interaction(req: AreaExecuteInteractionRequest) -> AreaExecuteInteractionResponse:
    save = get_current_save(default_session_id=req.session_id)
    if save.session_id != req.session_id:
        raise ValueError("session mismatch with current save")
    _ensure_area_snapshot(save)

    found = False
    for sub in save.area_snapshot.sub_zones:
        if any(it.interaction_id == req.interaction_id for it in sub.key_interactions):
            found = True
            break
    if not found:
        raise KeyError("AREA_INVALID_INTERACTION")

    if save.area_snapshot.clock is not None:
        save.area_snapshot.clock = _advance_clock(save.area_snapshot.clock, 1)
    save.game_logs.append(
        _new_game_log(
            req.session_id,
            "area_interaction_placeholder",
            f"触发交互 {req.interaction_id}（占位）",
            {"interaction_id": req.interaction_id},
        )
    )
    save_current(save)
    return AreaExecuteInteractionResponse(ok=True, status="placeholder", message="待开发")


def describe_behavior(session_id: str, movement_log: MovementLog, config: ChatConfig) -> BehaviorDescribeResponse:
    api_key = (config.openai_api_key or "").strip()
    model = (config.model or "").strip()
    if not api_key or not model:
        raise AIBehaviorError("缺少有效的模型配置或 API Key")

    try:
        client = OpenAI(api_key=api_key)
        prompt = (
            "你是跑团GM。"
            "请根据移动日志生成一段简短但有氛围感的叙事反馈，100-180字。"
            "你是故事叙述者，默认不要给编号选项，除非玩家明确要求给出选项。"
            "必须优先使用区块名称，不要使用 zone_xxx 这类内部ID。"
            "日志JSON如下："
            f"{json.dumps(movement_log.model_dump(mode='json'), ensure_ascii=False)}"
        )
        resp = client.chat.completions.create(
            model=model,
            temperature=min(max(config.temperature, 0), 2),
            messages=[
                {"role": "system", "content": config.gm_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        usage = resp.usage
        token_usage_store.add(
            session_id,
            "movement_narration",
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )
        narration = (resp.choices[0].message.content or "").strip()
        if not narration:
            raise AIBehaviorError("AI 未返回叙事文本")
        return BehaviorDescribeResponse(session_id=session_id, narration=narration)
    except AIBehaviorError:
        raise
    except Exception as exc:
        raise AIBehaviorError(str(exc)) from exc


