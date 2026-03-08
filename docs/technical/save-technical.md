# 存档系统技术文档（Save Technical）

## 设计来源
- `docs/design/gamedesign/savedesign.md`

更新于 `2026-03-08`。

## 1. 目标与边界
- 保持业务语义仍以 `SaveFile` 为统一逻辑对象。
- 将物理持久化从“单大 JSON”升级为“指针文件 + 分片 bundle”。
- 支持旧存档读取与新字段自动补齐。

## 2. 存储结构

### 2.1 入口指针
- `current-save.json`
- 仅保存：
  - 格式标识
  - bundle 目录名
  - `session_id`
  - `updated_at`

### 2.2 分片目录
- `current-save.json.bundle/manifest.json`
- `current-save.json.bundle/meta.json`
- `current-save.json.bundle/world_state.json`
- `current-save.json.bundle/map_snapshot.json`
- `current-save.json.bundle/area_snapshot.json`
- `current-save.json.bundle/player_data.json`
- `current-save.json.bundle/game_logs.json`
- `current-save.json.bundle/role_pool.json`
- `current-save.json.bundle/team_state.json`
- `current-save.json.bundle/quest_state.json`
- `current-save.json.bundle/encounter_state.json`
- `current-save.json.bundle/fate_state.json`

## 3. 逻辑层 `SaveFile`
当前位置：`backend/app/models/schemas.py`

当前核心字段：
- `world_state`
- `map_snapshot`
- `area_snapshot`
- `game_logs`
- `game_log_settings`
- `player_static_data`
- `player_runtime_data`
- `role_pool`
- `team_state`
- `quest_state`
- `encounter_state`
- `fate_state`

说明：
- `role_pool` 持久化 NPC 角色卡。
- `team_state` 持久化当前队伍、好感/信任、反应记录。
- `world_state` 持久化一致性 revision。

## 4. 读写策略

### 4.1 读取
- 优先读取 bundle manifest，并按分片组装成 `SaveFile`。
- 若 bundle 不存在，则回退读取旧版单文件 `SaveFile`。
- 若入口文件是 pointer，则按 `bundle_dir` 再继续解析。

### 4.2 写入
- 将 `SaveFile` 拆分为逻辑分片。
- 每个分片计算哈希，未变化时跳过重写。
- 更新 `manifest.json` 后，再写回入口指针文件。

## 5. 关键实现位置
- `backend/app/core/storage.py`
  - `read_save_payload(...)`
  - `write_save_payload(...)`
  - `_assemble_bundle(...)`
  - `_save_bundle_dir(...)`
- `backend/app/services/world_service.py`
  - `get_current_save(...)`
  - `save_current(...)`

## 6. 兼容性规则
- 新字段全部通过 Pydantic 默认值补齐。
- 旧存档自动补齐但不强制立即重写。
- 新保存统一写入 bundle。

当前已验证的兼容补齐方向：
- `role_pool`
- `world_state`
- `team_state`
- `quest_state`
- `encounter_state`
- `fate_state`

## 7. 日志与体积控制
- NPC 聊天日志按角色卡数组存储，仅保留最近 200 条。
- 队伍反应日志按 `team_state.reactions` 存储，仅保留最近 100 条。
- `game_logs` 作为全局审计日志，保留完整业务摘要，不直接替代角色卡局部历史。

## 8. 风险与回归点
- 风险：
  - manifest 与分片不一致
  - 新增状态分片漏写
  - 旧存档缺字段导致运行时读取异常
- 防线：
  - 分片原子写
  - 统一读取组装
  - 默认空存档兜底

回归重点：
- 新建存档与自动保存
- 读取旧存档
- 清空存档后重建
- `role_pool/team_state/world_state` 完整性
- NPC 聊天记录与队伍状态在重启后可恢复
