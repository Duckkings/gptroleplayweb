# Role Technical Addendum

更新日期：`2026-03-09`

## 本轮变化
- `NpcRoleCard` 新增 `desires`、`story_beats`、`last_public_turn_at`。
- 角色欲望与队友故事已从设计概念变为持久化状态。
- 公开场景导演器会把角色主动性当成真实运行状态，而不是纯文案提示。

## 当前落地点
- `backend/app/services/roleplay_service.py`
- `backend/app/services/public_scene_service.py`
- `frontend/src/components/TeamPanel.tsx`
- `frontend/src/components/RoleProfileModal.tsx`

## 当前规则摘要
- NPC 自动补齐 `1-2` 个 desire
- 队友自动补齐 `2` 个 story beat
- desire/story 可通过 scene events 浮出
- 队友故事默认非模态

