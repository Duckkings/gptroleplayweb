# 存档系统技术文档

更新日期：`2026-03-09`

## 1. 目标
- 业务层统一以 `SaveFile` 为逻辑对象。
- 物理层采用 pointer + bundle 分片。
- 旧存档通过默认值和服务层补齐兼容，不要求人工迁移。

## 2. SaveFile 当前关键字段
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
- `reputation_state`

## 3. Bundle 分片
当前 bundle 目录中包含：
- `manifest.json`
- `meta.json`
- `world_state.json`
- `map_snapshot.json`
- `area_snapshot.json`
- `player_data.json`
- `game_logs.json`
- `role_pool.json`
- `team_state.json`
- `quest_state.json`
- `encounter_state.json`
- `fate_state.json`
- `reputation_state.json`

## 4. 新增持久化结构

### 4.1 `reputation_state`
位置：
- `SaveFile.reputation_state`
- `current-save.json.bundle/reputation_state.json`

结构：
- `version`
- `entries`
- `updated_at`

每条 `SubZoneReputationEntry` 包含：
- `sub_zone_id`
- `zone_id`
- `score`
- `band`
- `recent_reasons`
- `updated_at`

### 4.2 `NpcRoleCard`
新增持久化字段：
- `desires`
- `story_beats`
- `last_public_turn_at`

### 4.3 `EncounterEntry`
新增持久化字段：
- `participant_role_ids`
- `situation_start_value`
- `situation_value`
- `situation_trend`
- `last_outcome_package`

### 4.4 `EncounterResolution`
新增结算字段：
- `situation_delta`
- `situation_value_after`
- `reputation_delta`
- `applied_outcome_summaries`

## 5. 兼容策略

### 5.1 Pydantic 默认补齐
当前兼容策略优先依赖 schema 默认值：
- 旧存档缺 `reputation_state` 时自动补空结构
- 旧角色缺 `desires/story_beats` 时自动补空列表
- 旧遭遇缺 `situation_value` 等字段时自动补默认值

### 5.2 服务层补齐
仅靠默认值不够的结构，由服务层在读写或运行时补齐：
- `ensure_reputation_state(...)`
- `ensure_roleplay_state_for_save(...)`
- `_initialize_encounter_state(...)`

这类补齐会在首次运行相关功能时把旧档升级到当前逻辑状态。

## 6. 读写策略

### 6.1 读取
- 优先读取 bundle manifest，再组装 `SaveFile`
- 若没有 bundle，则回退读取旧版单文件存档
- 若当前文件是 pointer，则先解析 `bundle_dir`

### 6.2 写入
- 将 `SaveFile` 拆分为逻辑分片
- 按分片 hash 判断是否重写
- 更新 manifest 后再回写 pointer 文件

## 7. 存档与玩法系统的关系
- `role_pool` 既承载 NPC 基础卡，也承载 desire/story、对话日志和公开轮次记忆
- `team_state` 持久化队友关系快照和队伍反应
- `encounter_state` 持久化活跃遭遇、局势值、历史记录
- `reputation_state` 持久化子区块声望

## 8. 当前风险与防线

### 8.1 风险
- 新分片遗漏写入
- 旧档读取后状态不完整
- 角色或遭遇字段补齐只做了 schema，未做运行时初始化

### 8.2 防线
- `backend/app/core/storage.py` 统一管理 bundle 读写
- 关键系统在进入运行逻辑前显式调用初始化函数
- 单测覆盖旧档兼容、运行时补齐和新字段落库

## 9. 回归测试
- `backend/tests/test_role_system.py`
- `backend/tests/test_encounter_service.py`
- `backend/tests/test_team_service.py`
- `backend/tests/test_inventory_interaction.py`

