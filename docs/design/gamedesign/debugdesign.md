# Debug 面板模块设计

## 模块目标
- 为开发与联调提供集中入口与可观测信息。
- 不污染正式游玩体验。

## 核心体验规则
- 默认折叠，仅开发场景使用。
- 提供模块入口、调试摘要、路径管理与高风险操作入口。

## 参数枚举（设计层）
- 可见性：`dev_only`、`collapsed_by_default`
- 子功能入口：`world_map`、`player_panel`、`battle_test`、`npc_gen`
- 存档操作：`pick_save_path`、`clear_save`
- NPC 查看：提供按钮弹出列表，支持名称搜索与点击查看 NPC 角色卡

## 安全约束
- 禁止展示敏感信息：`openai_api_key`、`Authorization`、完整系统提示词。
- 调试输出需脱敏后展示。

## 验收标准
- 可通过面板进入核心调试子模块。
- API 摘要可用于定位失败原因。
- 敏感信息不会出现在 UI 调试区域。
