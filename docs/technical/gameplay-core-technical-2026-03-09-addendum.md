# Gameplay Core Addendum

更新日期：`2026-03-09`

## 本轮变化
- 主聊天正式加入 `route_main_turn_intent(...)`，先做后端动作判定，再决定是否需要模型自由叙事。
- 公开区域反应从旧的启发式推进改为 `public_scene_service.py` 的严格轮值导演器。
- 主聊天不再只返回 GM 正文；关键世界推进改为通过 `scene_events` 向前端同步。

## 当前新增事件
- `public_actor_resolution`
- `role_desire_surface`
- `companion_story_surface`
- `reputation_update`
- `encounter_situation_update`

## 当前新增读取接口
- `GET /api/v1/reputation/current`
- `GET /api/v1/role-drives`
- `GET /api/v1/scene/public-state`

## 实施结果
- 主聊天中的明确玩法动作现在能优先触发真实后端逻辑。
- 公开场景推进和遭遇推进已经打通，不再各自独立漂移。

