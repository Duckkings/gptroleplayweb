# 可交互物、装备与武器设计

更新日期：2026-03-15

## 1. 目标

这份设计用于把当前项目里已经分散存在的三类内容收口成一套统一规则：

- 场景中的可交互物
- 背包中的物品与装备
- 战斗中可被使用的武器与道具

本设计的目标不是单独再造一个“物品小游戏系统”，而是让以下模块共享同一套物品真相：

- 主聊天公开行为
- NPC 单聊
- 遭遇与世界推进
- 独立战斗模块
- 队友与 NPC 行动
- 地图子区块内容
- 日志与长期记忆

## 2. 设计原则

### 2.1 同一件东西只能有一份正式定义

例如一把刀：

- 在背包里它是物品
- 装备后它是武器
- 丢到地上后它可以成为场景可交互物
- 战斗中它提供攻击数据

但它本体仍然只是一份 `ItemInstance`，不能为不同模块复制出不同真相。

### 2.2 场景可交互物与背包物品要能双向流动

可交互物不是单纯“背景描述”。它应支持：

- 观察
- 拾取
- 使用
- 装备
- 破坏
- 触发
- 交给 NPC
- 丢回场景

也就是说：

- 场景中的东西可以进入背包
- 背包里的东西也可以重新变成场景中的可交互物

### 2.3 装备与武器不单独做成另一套库存

装备不是和背包平行的新仓库，而是：

- 背包中某个物品实例被放入了装备槽

因此：

- 装备位只记录 `item_id`
- 真正的物品内容仍从库存里读取

### 2.4 战斗先支持“可用”，再支持“复杂”

当前项目已经有独立战斗沙盒第一阶段，因此物品系统必须兼容：

- 第一阶段先支持最小白名单
- 不要求一步到位复刻完整 DND5E 武器与道具大全

## 3. 范围与边界

### 本期纳入

- 可交互物分类与状态模型
- 背包物品基础模型
- 装备槽模型
- 武器与护甲模型
- 物品与主聊天/NPC/遭遇/战斗的联动规则
- 物品交互的日志与可见结果

### 本期不纳入

- 完整制造/合成系统
- 复杂耐久系统
- 完整弹药经济
- 复杂附魔锻造
- 商店经济平衡
- 完整 5E 武器词条与专长

## 4. 统一对象模型

## 4.1 场景可交互物与背包物品的关系

统一采用三层模型：

### A. ItemDefinition

定义“这是什么东西”。

例如：

- 铁匕首
- 旧木盾
- 绷带包
- 火油瓶
- 生锈钥匙

这是模板层，不带归属和数量。

### B. ItemInstance

定义“这件具体物品实例”。

例如：

- 玩家背包里的第 3 把匕首
- 酒馆柜台上的那瓶火油
- 倒地敌人身上的那面盾

它带：

- 唯一 id
- 当前归属
- 当前所在位置
- 当前数量/次数/状态

### C. SceneInteractable

定义“当前场景里能被交互的对象”。

它既可以绑定 `item_instance_id`，也可以是纯场景对象。

例如：

- 绑定物品实例：地上的匕首、桌上的药瓶
- 纯场景对象：门、窗、柜子、祭坛、陷阱绳索、松动石砖

因此：

- 不是所有可交互物都能进入背包
- 但所有可拾取的可交互物都应能映射到 `ItemInstance`

## 4.2 ItemDefinition

建议字段：

```ts
type ItemDefinition = {
  definition_id: string;
  name: string;
  item_kind: 'weapon' | 'armor' | 'shield' | 'consumable' | 'tool' | 'quest' | 'material' | 'throwable' | 'trinket';
  sub_kind?: string | null;
  description: string;
  rarity: 'common' | 'uncommon' | 'rare' | 'epic' | 'legendary';
  weight: number;
  stackable: boolean;
  max_stack?: number | null;
  value_gp?: number | null;
  tags: string[];
  equip_slot_tags: string[];
  interaction_tags: string[];
  combat_tags: string[];
  inspect_prompt_hint?: string | null;
  use_prompt_hint?: string | null;
};
```

语义：

- `item_kind` 决定规则大类
- `equip_slot_tags` 决定是否能装备以及能装到哪里
- `interaction_tags` 决定在主聊天中可触发哪些交互按钮
- `combat_tags` 决定能否在战斗中使用

## 4.3 ItemInstance

建议字段：

```ts
type ItemInstance = {
  item_id: string;
  definition_id: string;
  custom_name?: string | null;
  owner_kind: 'player' | 'team_member' | 'npc' | 'scene' | 'none';
  owner_id?: string | null;
  zone_id?: string | null;
  sub_zone_id?: string | null;
  quantity: number;
  charges_current?: number | null;
  charges_max?: number | null;
  durability_current?: number | null;
  durability_max?: number | null;
  status_tags: string[];
  metadata: Record<string, unknown>;
};
```

规则：

- 背包物品通过 `owner_kind + owner_id` 归属到角色
- 地上物品通过 `owner_kind='scene'` 并带 `zone_id/sub_zone_id`
- 装备不复制物品，只引用 `item_id`

## 4.4 SceneInteractable

建议字段：

```ts
type SceneInteractable = {
  interactable_id: string;
  name: string;
  interactable_kind: 'loot' | 'container' | 'door' | 'mechanism' | 'hazard' | 'evidence' | 'furniture' | 'item_proxy';
  zone_id: string;
  sub_zone_id: string;
  description: string;
  visible: boolean;
  hidden: boolean;
  locked: boolean;
  broken: boolean;
  item_instance_id?: string | null;
  tags: string[];
  interaction_options: string[];
  state_summary?: string | null;
  metadata: Record<string, unknown>;
};
```

说明：

- `item_proxy` 表示“这其实是一个物品在场景里的展示代理”
- `container` 可承载多个 `item_instance_id`
- `hazard` 主要用于环境交互与战斗联动

## 5. 交互分类

## 5.1 场景可交互物分类

建议分为 6 大类：

### 1. 可拾取物

例如：

- 匕首
- 钥匙
- 药瓶
- 火油
- 信件

支持：

- 观察
- 拾取
- 丢弃
- 交给别人
- 战斗中使用

### 2. 容器类

例如：

- 箱子
- 柜子
- 尸体
- 行囊
- 衣柜

支持：

- 观察
- 搜索
- 打开
- 上锁/解锁
- 取出物品
- 放入物品

### 3. 门/路径类

例如：

- 门
- 栅栏
- 地窖入口
- 暗门
- 楼梯口

支持：

- 观察
- 打开/关闭
- 破坏
- 上锁/解锁
- 进入/离开

### 4. 机关类

例如：

- 拉杆
- 铃铛
- 阵法
- 绳索机关

支持：

- 观察
- 触发
- 解除
- 破坏
- 复位

### 5. 环境危险类

例如：

- 火盆
- 塌方边缘
- 易燃酒桶
- 松动吊灯

支持：

- 观察
- 触发
- 推倒
- 点燃
- 利用

### 6. 线索类

例如：

- 血迹
- 爪痕
- 笔记
- 地图碎片

支持：

- 观察
- 收起
- 比对
- 向 NPC 出示
- 作为遭遇推进证据

## 5.2 背包物品分类

背包中的物品建议分为：

- 武器
- 护甲
- 盾牌
- 消耗品
- 工具
- 投掷物
- 任务物品
- 材料
- 饰品

## 6. 装备系统设计

## 6.1 装备槽

建议使用明确装备槽，而不是“只记录当前武器/当前护甲”。

第一阶段正式装备槽：

- `main_hand`
- `off_hand`
- `armor`
- `accessory_1`
- `accessory_2`
- `quick_item_1`
- `quick_item_2`
- `quick_item_3`

说明：

- 当前代码已经有“当前武器 / 当前护甲”的实现，后续应平滑升级为标准槽位
- 第一阶段战斗模块可只真正使用：
  - `main_hand`
  - `off_hand`
  - `armor`
  - `quick_item_*`

## 6.2 装备规则

### 武器

- 主手可装备一件主武器
- 副手可装备：
  - 盾牌
  - 副手武器
  - 轻型工具

### 护甲

- 护甲槽同一时间只允许一件
- 盾牌不占护甲槽，占副手槽

### 快捷物品

- 快捷槽用于：
  - 药剂
  - 绷带
  - 小型投掷物

第一阶段战斗中优先支持快捷物品调用。

## 6.3 装备与背包的关系

装备规则固定为：

- 只能装备背包中真实存在的 `item_id`
- 卸下后物品仍留在背包
- 如果物品被移除/消耗/丢弃，装备槽必须自动失效

## 8. 护甲与盾牌设计

## 8.1 护甲分类

建议统一分为：

- `clothing`
- `light_armor`
- `medium_armor`
- `heavy_armor`
- `shield`

## 8.2 护甲字段

```ts
type ArmorProfile = {
  armor_class_base: number;
  dex_cap?: number | null;
  stealth_penalty?: boolean;
  speed_penalty?: boolean;
  traits: string[];
};
```

## ~~8.3 AC 规则~~

~~与当前战斗设计兼容，建议正式写法为：~~

- ~~无护甲：`10 + 敏捷调整值`~~
- ~~轻甲：`armor_class_base + 敏捷调整值`~~
- ~~中甲：`armor_class_base + min(敏捷调整值, dex_cap)`~~
- ~~重甲：`armor_class_base`~~
- ~~盾牌：在最终 AC 上 `+2`~~

~~这样比早期文档里“AC = 武器攻击力 + 力量/敏捷加值”更一致，也更契合你当前战斗方向。~~

## 9. 消耗品与投掷物

## 9.1 消耗品

建议优先支持：

- 回复类：药剂、绷带、急救包
- 增益类：临时强化剂、护身符、短效药丸
- 功能类：钥匙、照明、破门工具

第一阶段战斗完整支持范围：

- 回复类

其余可先存在于主聊天与背包层，逐步接入战斗。

## 9.2 投掷物

建议单列一类，不和普通消耗品混淆：

- 飞刀
- 石块
- 火油瓶
- 沙土包
- 小型爆鸣物

投掷物的作用不只有伤害，也可以：

- 制造短暂失明
- 点燃场景
- 改变站位
- 触发玩家反应检定

## 10. 可交互物的交互动作

建议统一交互动作枚举：

- `inspect`
- `take`
- `drop`
- `equip`
- `unequip`
- `use`
- `throw`
- `give`
- `open`
- `close`
- `lock`
- `unlock`
- `trigger`
- `disable`
- `break`
- `move`
- `compare`

说明：

- 主聊天和 NPC 单聊里，AI 只需要决定“这次意图是否会落到这些动作之一”
- 后端规则层负责做合法性校验和状态落地

## 11. 与主聊天的联动

## 11.1 公开行为中的物品使用

当玩家在主聊天里说：

- “我拿起桌上的酒瓶”
- “我把钥匙插进锁孔”
- “我掏出匕首威胁他”
- “我把绷带给队友”

系统应优先尝试把这些行为映射为：

- 场景可交互物动作
- 背包物品动作
- 装备动作

而不是每次都只当作纯文字叙事。

## 11.2 公开行为中的装备影响

装备应影响：

- NPC 对玩家危险感知
- 主聊天公开行动的可行性
- 是否触发额外检定
- 区域名声的变动幅度

例如：

- 赤手和持刀威吓的社会后果不应相同
- 在低危险城镇里公然持武器施压，应更容易降低区域名声

## 12. 与 NPC 单聊的联动

NPC 单聊中，物品与装备至少支持：

- 向 NPC 出示
- 递交
- 交换
- 用物品辅助说服
- 用武器造成威慑

建议把“物品是否被看见”作为上下文的一部分。

例如：

- 玩家只是背着剑，和玩家已经拔剑，NPC 反应不应一样

## 13. 与遭遇和世界推进的联动

可交互物应能参与：

- 遭遇推进
- 世界推进
- 新地点生成
- 线索发现

典型场景：

- 发现血迹、碎片、钥匙，作为线索类可交互物进入场景
- 世界推进后，某地出现“被翻倒的药箱”“断裂的门闩”，这些应是正式可交互物，而不是只写一句描述

## 14. 与战斗模块的联动

## 14.1 第一阶段战斗白名单

当前独立战斗模块第一阶段建议这样接：

### 完整支持

- 主手武器攻击
- 副手盾牌 AC 修正
- 回复类快捷物品
- 观察获得下一击 `+2`

### 部分支持

- 投掷物
- 临时增益物品
- 场景危险物触发

### 后续支持

- 武器特技
- 护甲熟练惩罚
- 弹药
- 武器专长
- 复杂双持

## 14.2 战斗中的场景可交互物

战斗中建议优先支持这些场景物：

- 门
- 掩体
- 可推翻家具
- 易燃物
- 高低差位置
- 绳索/吊灯/脆弱支撑物

这些对象要能通过 `SceneInteractable` 的 `interaction_options` 进入战斗动作选择，而不是重新做一套战斗专用场景物模型。

## 14.3 玩家反应检定

战斗中的场景可交互物与投掷物，要能触发玩家反应检定。

例如：

- 敌人踢翻火盆
- 吊灯砸落
- 火油瓶爆开

这些都应遵循你已经确认的规则：

- 先形成威胁
- 弹玩家骰子框
- 再结算后果

## 15. 与日志和长期记忆的联动

每次重要物品交互应写日志，但粒度要克制。

建议只记录：

- 关键物品获得
- 关键物品失去
- 装备变化
- 关键线索类可交互物被发现/使用
- 战斗中关键物品使用

不建议把每次查看普通小物件都写成长日志。

## 16. AI 生成与补图规则

当 AI 生成新地点、遭遇或新场景时，可交互物应作为结构化输出的一部分，而不是纯叙事附带。

建议 AI 输出结构统一支持：

```json
{
  "scene_interactables": [
    {
      "name": "翻倒的药箱",
      "interactable_kind": "container",
      "description": "木箱盖子裂开，里面散落着几卷绷带和一瓶浑浊药剂。",
      "interaction_options": ["inspect", "open", "take"]
    }
  ]
}
```

这样地图、主聊天、遭遇、战斗都能消费同一批场景对象。

## 17. 数据真相建议

建议后续代码层统一采用以下关系：

- `InventoryState`
  - 持有 `ItemInstance[]`
- `EquipmentState`
  - 槽位只引用 `item_id`
- `SceneInteractableState`
  - 当前子区块可交互对象
- `ItemDefinitionRegistry`
  - 静态模板库

模块读取优先顺序：

1. 定义层：`ItemDefinition`
2. 实例层：`ItemInstance`
3. 场景层：`SceneInteractable`
4. 展示层：背包、装备面板、战斗面板、场景交互面板

## 18. 分期建议

### P1：统一文档与最小规则

- 明确可交互物、装备、武器统一定义
- 背包与装备槽共享一份物品真相
- 独立战斗模块只支持最小武器/护甲/回复类物品

### P2：场景交互闭环

- 场景可交互物正式结构化
- 可拾取/可放回
- 容器与门机制完善
- NPC 单聊与主聊天更稳定地消费这些对象

### P3：高级装备与战斗扩展

- 护甲惩罚
- 武器特技
- 投掷物
- 复杂道具
- 附魔与稀有度系统

## 19. 结论

最契合当前项目的做法不是把“可交互物、装备、武器”拆成三套互不相干的系统，而是：

- 用一套物品定义与实例模型承接所有模块
- 用场景可交互物模型承接地图与叙事现场
- 用装备槽承接角色状态
- 用武器/护甲配置承接战斗规则

这样主聊天、NPC、遭遇、地图和战斗才能真正共享数据，而不是各自再造一套“看起来像同一个东西”的结构。
