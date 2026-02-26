# 存档系统技术文档（Save Technical）

## 设计来源
- docs/design/gamedesign/savedesign.md

## 1. 目标与边界
- 保持业务语义仍以 `SaveFile` 为统一逻辑对象。
- 将物理持久化从“单大 JSON”升级为“指针文件 + 分片 bundle”。
- 兼容旧存档读取，避免历史数据失效。

## 2. 存储结构
### 2.1 入口文件（Pointer）
- `current-save.json`
- 内容仅保存格式标识、bundle 目录、会话与更新时间等轻量信息。

### 2.2 分片目录（Bundle）
- `current-save.json.bundle/manifest.json`
- `current-save.json.bundle/meta.json`
- `current-save.json.bundle/map_snapshot.json`
- `current-save.json.bundle/area_snapshot.json`
- `current-save.json.bundle/player_data.json`
- `current-save.json.bundle/game_logs.json`

## 3. 读写策略
### 3.1 读取
- 优先读取 bundle manifest 并组装为 `SaveFile` 结构。
- 若 bundle 不存在，则回退读取旧版单文件 `SaveFile`。
- 若遇到 pointer 文件，按 `bundle_dir` 继续解析。

### 3.2 写入
- 将 `SaveFile` 拆分为 `meta/map/area/player/logs` 五类分片。
- 每个分片计算内容哈希；未变化分片跳过重写。
- 更新 `manifest.json` 后写回 `current-save.json` 指针。

## 4. 关键实现位置
- `backend/app/core/storage.py`
  - `read_save_payload(save_path)`
  - `write_save_payload(save_path, payload)`
  - `_save_bundle_dir(...)`
  - `_assemble_bundle(...)`
- `backend/app/services/world_service.py`
  - `get_current_save(...)`
  - `save_current(...)`
- `SaveFile` 结构已扩展：`role_pool` 存储已生成 NPC 角色卡，随存档分片保存
- `role_pool[*].dialogue_logs` 持久化 NPC 结构化聊天记录（含世界时间、说话方、文本）

## 5. API 影响
- 外部 API 无新增/破坏性变更：
  - `GET /api/v1/saves/current`
  - `POST /api/v1/saves/current`
  - `POST /api/v1/saves/import`
  - `POST /api/v1/saves/clear`
  - `GET/POST /api/v1/saves/path`
- 变更仅在后端持久化实现层。

## 6. 兼容性规则
- `backward_read_legacy`：允许读取旧单文件。
- `forward_write_bundle`：新写入统一采用 bundle。
- schema 仍由 `SaveFile` / Pydantic 控制，不改变业务字段语义。

## 7. 风险与回归点
- 风险：manifest 与分片不一致导致加载失败。
- 防线：分片原子写、统一读取组装、默认空存档兜底。
- 回归重点：
  - 新建存档与自动保存
  - 读取旧存档
  - 清空存档后重建
  - 地图/角色/日志字段完整性
  - NPC 聊天记录写回角色卡并可在重启后恢复

## 8. 体积控制补充
- NPC 聊天日志按角色卡内数组存储，后端保留最近 200 条记录。
- 该策略用于控制 `role_pool` 分片增长，避免单角色长期对话导致存档失控膨胀。
