# 游戏设计总纲

> 本文件只保留产品总纲与模块导航；具体模块规则请阅读各模块设计文档；数据结构/API/状态机请阅读技术文档。

## 文档定位
- 本文档定义产品目标、体验原则、阶段范围与文档索引。
- 不承载具体 JSON 结构、接口契约、状态机或错误码。

## 游戏宏观设计
- 游戏有硬指标：时间。任何行为都会消耗时间，消耗由逻辑系统结算。
- 游戏有经济压力：玩家通过任务/战斗获取金钱，需按周期支付冒险者工会会费。
- 核心体验目标：引导玩家专注角色扮演与选择后果，而非纯数值刷取。

## 范围与阶段
- 当前阶段（M1）：Debug 驱动的世界地图、存档、玩家数据面板、聊天闭环。
- 非当前阶段：完整战斗系统、深度 NPC 行为、长期经济系统。

## 设计原则
- 规则先于表现：先保证行为可解释，再优化表现层。
- 逻辑与叙事解耦：AI 负责语义表达，逻辑层负责状态一致性。
- 渐进扩展：优先保证存档兼容与模块边界稳定。

## 模块设计文档（Design）
- 主流程：`docs/design/gamedesign/playflowdesign.md`
- 区块系统：`docs/design/gamedesign/areadesign.md`
- 角色系统：`docs/design/gamedesign/roledesign.md`
- 遭遇系统：`docs/design/gamedesign/encounterdesign.md`
- 互动对象：`docs/design/gamedesign/interactitemdesign.md`
- 任务系统：`docs/design/gamedesign/questdesign.md`
- 世界地图 UI：`docs/design/gamedesign/worldmapdesign.md`
- 存档与路径：`docs/design/gamedesign/savedesign.md`
- Debug 面板：`docs/design/gamedesign/debugdesign.md`

## 技术文档（Technical）
- 总技术文档：`docs/technical/technical.md`
- 核心玩法技术：`docs/technical/gameplay-core-technical.md`
- 区块技术：`docs/technical/area-technical.md`
- 角色技术：`docs/technical/role-technical.md`
- 存档技术：`docs/technical/save-technical.md`
- AI 工具协议：`docs/technical/ai-tool-protocol.md`
- MVP 架构契约：`docs/technical/mvp-architecture.md`

## 文档维护规则
- 新增功能先补模块设计文档，再补对应技术文档。
- 设计文档仅保留：目标、规则、参数枚举、交互约束、验收标准。
- 技术文档负责：JSON 结构、API 契约、状态机、错误码、实现策略。



