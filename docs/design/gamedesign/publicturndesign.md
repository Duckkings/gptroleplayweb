# 主聊天公开回合设计

本文档只保留公开回合总览。互动、攻击、对抗、AOE、伤害结算的细则统一引用：

- [publicturninteractiondesign.md](./publicturninteractiondesign.md)

## 1. 设计目标

公开回合用于承载主聊天里的公开场景推进，目标是：

- 让玩家、队友、在场 NPC、隐藏 NPC、环境都能在同一套回合里推进
- 支持社交、探索、攻击、AOE、环境破坏混合结算
- 把结构化状态影响写回场景，而不是只产出叙事文本
- 在必要时暂停给玩家输入，在恢复后继续同一轮

## 2. 回合结构

每个公开回合包含三个阶段：

1. 抢先声明
2. 常规推进
3. 事态推进 / GM push

## 3. 玩家入口

玩家有两个入口：

- `开始下一回合`
  - 不声明抢先
  - 直接进入常规推进
- `优先行动`
  - 玩家和其他有意抢先的角色一起进入抢先声明
  - 根据敏捷与 d20 决定抢先顺序

## 4. 抢先规则

- 角色在抢先阶段已经行动过，则不会在本轮常规推进阶段再次行动。
- 玩家在抢先阶段通过互动回应、攻击回应、攻击对抗、普通对抗实际行动过，也视为本轮已执行。

## 5. 常规推进

常规推进阶段负责处理：

- 玩家主动行动
- NPC / 队友的公开行动
- 社交、探索、攻击、AOE 等公开场景结算

详细的互动与攻击分流见：

- [publicturninteractiondesign.md](./publicturninteractiondesign.md)

## 6. 结构化结果

公开回合每个已结算动作都必须产出：

- settlement entry
- narration
- impacts
- relation / affinity changes
- situation delta
- reputation delta
- environment shift
- hp changes

## 7. 环境危险与事态推进

- 环境风险分为：`stable / risky / collapse`
- 局势值和环境风险共同决定事态推进压力
- 回合末可触发 GM push 或额外场景变化

## 8. 遭遇与隐藏角色

- `encounter` 是公开回合里的临时事件实例，不是平行系统
- 隐藏角色平时不公开参与排序与描述
- 若被 AOE 纳入威胁范围，则立即显形并加入当前攻击结算

## 9. 文档归属

- 本文档：公开回合总览、阶段、入口、风险、遭遇关系
- [publicturninteractiondesign.md](./publicturninteractiondesign.md)：互动与攻击唯一详细口径
