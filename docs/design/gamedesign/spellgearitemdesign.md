# 法术、武装与道具使用设计

更新日期：2026-03-21
状态：草案，待审阅

## 1. 文档目标

这份设计文档用于统一以下三类系统的“来源、持有、校验、消耗、使用结果”规则：

- 法术
- 武装
  - 武器
  - 护甲
  - 盾牌
  - 后续可扩展饰品、法器、弹药位
- 道具
  - 消耗品
  - 工具
  - 投掷物
  - 任务物
  - 特殊剧情物

这份文档不替代现有：

- [角色框架与玩家数据设计](c:/Project/gptroleplayweb/docs/design/gamedesign/roledesign.md)
- [可交互物、装备与武器设计](c:/Project/gptroleplayweb/docs/design/gamedesign/interactitemdesign.md)
- [公开回合互动设计](c:/Project/gptroleplayweb/docs/design/gamedesign/publicturninteractiondesign.md)
- [战斗系统设计（已弃用归档）](c:/Project/gptroleplayweb/docs/design/gamedesign/trash/battlesystem.md)

而是给它们补上一层统一规则：
“角色为什么能用、什么时候能用、用了要扣什么、扣失败怎么办、哪些判断交给 AI、哪些判断必须由后端规则层保证。”

## 2. 当前缺口

当前仓库已经有：

- 角色背包与装备位
- 法术列表与法术位
- 武器/装备/法术模板库
- 主聊天、公开回合、战斗中的攻击/物品使用入口

但还缺三块关键闭环：

### 2.1 缺少玩家初始构筑

当前玩家角色没有正式的“新游戏构筑流程”。
法术、武装、道具更多是编辑面板或调试入口直接改出来的，而不是从角色职业、背景、起始包、学习来源中生长出来。

### 2.2 缺少统一使用校验

当前系统能“存着这些东西”，但还没有一套统一判断：

- 这个角色是否真的会这个法术
- 这个武器是否真的装备在身上
- 这个道具是否真的在背包里
- 当前状态下能不能用
- 使用后该扣什么资源

### 2.3 缺少统一费用与消耗规则

当前法术位、体力、数量、次数、充能、动作经济，还没有被统一接进一条使用结算链。
不同模块会各自判断，但缺少一套共同口径。

## 3. 核心设计原则

### 3.1 使用权必须来自可追踪来源

角色能使用法术、武装、道具，必须能追溯到明确来源：

- 初始构筑
- 剧情奖励
- 掉落
- 商店/购买
- 学习
- 抄录/制作
- 队友转交
- Debug 注入

不允许出现“AI 觉得合理，所以默认角色会这个法术/身上有这件装备”这种无来源授权。

### 3.2 AI 负责理解，后端负责裁决

AI 可以负责：

- 理解玩家自然语言
- 在候选池中选择最可能的法术/装备/道具
- 生成叙事
- 生成上下文相关的行为后果

后端必须负责：

- 所有权校验
- 装备状态校验
- 资源充足性校验
- 使用条件校验
- 消耗落盘
- 一致性与回滚

### 3.3 不允许靠前后端字符串猜“会不会用”

法术、武装、道具的识别，必须尽量走：

- AI 从候选池返回稳定 ID
- 后端按 ID 查定义与实例

不再依赖：

- 关键词词表
- 中英文名称硬编码匹配
- 前端本地正则猜类型

### 3.4 “能使用”与“使用成功”是两回事

要先区分两层：

- 使用合法性
  - 角色有没有资格、资源、目标、上下文去尝试
- 结果结算
  - 使用后是否命中、是否被阻止、是否造成伤害或效果

一个行为可以“允许尝试但最终失败”，但不能“根本不合法却被当作已经施放”。

## 4. 统一对象层

本设计把三类对象拆成四层：

### 4.1 定义层 Definition

定义“这是什么东西/法术/武装”。

- `ItemDefinition`
- `EquipmentDefinition`
- `SpellDefinition`

定义层不记录归属，不记录当前拥有者。

### 4.2 实例层 Instance

定义“角色当前真正持有的这一件东西”。

- 背包中的药水实例
- 装备中的长剑实例
- 地上掉落的火油瓶实例

法术通常不是实例，而是“已学会能力”；
但卷轴、魔杖、充能法器这种“承载法术效果的物品”仍属于实例层。

### 4.3 授权层 Entitlement

定义“角色为什么能使用”。

例如：

- 起始职业授予的已知法术
- 背景授予的工具熟练
- 起始装备包授予的长剑
- 升级学会的法术
- 任务奖励发放的药水

授权层是本设计新增的核心概念。
它负责把“来源”和“可用权”绑定起来。

### 4.4 资源层 Resource

定义“使用要扣什么”。

例如：

- 法术位
- 体力
- 数量
- 充能次数
- 每轮次数
- 每短休/长休次数
- 金币/材料

## 5.构筑设计迁移至playerandpawnbuilddesign.md

## 6. 法术、武装、道具的来源规则

### 6.1 法术来源

法术的合法来源只允许：

- 起始职业构筑
- 升级学习
- 任务/剧情授予
- 抄录/研究学会
- 特殊装备临时授予
- Debug 授予

法术不应因为“AI 觉得角色像法师”就临时拥有。

### 6.2 武装来源

武器/护甲/盾牌的来源只允许：

- 起始装备包
- 掉落
- 商店
- 制作
- 剧情赠与
- Debug 注入

### 6.3 道具来源

道具来源允许：

- 起始补给包
- 场景拾取
- 遭遇奖励
- 任务奖励
- 购买
- 制作
- 队友/NPC 转交
- Debug 注入

## 7. 统一使用校验规则

所有模块在“尝试使用法术/武装/道具”前，都必须经过统一校验核。

## 7.1 校验阶段顺序

建议固定为：

1. 识别阶段
2. 所有权阶段
3. 状态阶段
4. 资源阶段
5. 场景阶段
6. 动作经济阶段
7. 结算阶段

## 7.2 识别阶段

输入可以是自然语言：

- “我念火球术炸他们”
- “我拔剑砍向前面的盗匪”
- “我给队友灌治疗药水”

识别规则：

- 后端先准备候选池
  - 当前已装备武器
  - 当前可用快捷物品
  - 当前背包可使用道具
  - 当前已知法术
- AI 必须从候选池中返回稳定 ID
  - `spell_definition_id`
  - `equipment_definition_id`
  - `item_definition_id`
  - `item_instance_id`
- AI 也要返回 `use_mode`
  - `attack`
  - `consume`
  - `equip`
  - `inspect`
  - `throw`
  - `give`
  - `cast`
  - `channel`

如果 AI 没有选中候选池中的合法对象，则后端不能直接放行。

## 7.3 所有权阶段

### 法术

必须满足：

- 角色已知该法术，或
- 当前装备/持有的物品明确授予该法术使用权

### 武装

必须满足：

- 该实例存在于角色背包中，且
- 对应装备位已装配，或
- 明确允许“从背包即时取出使用”

### 道具

必须满足：

- 该实例真实存在于角色背包或当前可触达场景中
- 数量/充能/次数大于 0

## 7.4 状态阶段

要检查角色当前状态是否允许使用：

- 是否死亡/濒死
- 是否被束缚
- 是否失去持握能力
- 是否沉默
- 是否失去施法专注能力
- 是否双手被占满
- 是否目标不可见
- 是否被地形阻断

### 示例

- 被沉默不能施放需要言语成分的法术
- 双手都被占且无空手，不能使用需要手部操作的道具
- 未装备武器时，不能声明“用我的长弓攻击”

## 7.5 资源阶段

要检查：

- 法术位是否够
- 体力是否够
- 充能是否够
- 数量是否够
- 每轮次数是否够
- 休息恢复次数是否已用尽
- 材料是否齐全

## 7.6 场景阶段

要检查：

- 是否有合法目标
- 距离是否允许
- 当前模式是否允许
  - 主聊天
  - NPC 单聊
  - 公开回合
  - 战斗
- 当前地点是否允许该使用

### 示例

- 在普通社交聊天里可以“准备施法威吓”，但不能直接跳过公开回合规则进行范围攻击结算
- 对已离场目标不能继续使用单体法术
- 需要接触的道具不能对远处目标直接结算

## 7.7 动作经济阶段

要检查本轮是否还有可用动作：

- 主动作
- 附赠动作
- 反应
- 自由交互

不同模块口径统一：

- 战斗：严格使用动作经济
- 公开回合：映射为“本轮可声明一次主要行为”
- 主聊天/NPC 单聊：映射为时间与检定成本，不直接显示 action economy，但后台仍记录行为类别

## 8. 费用与消耗设计

## 8.1 统一费用类型

每次合法使用都可以声明一个或多个费用：

- `spell_slot`
- `stamina`
- `item_quantity`
- `charge`
- `ammo`
- `gold`
- `material`
- `once_per_turn`
- `once_per_short_rest`
- `once_per_long_rest`
- `time_min`

## 8.2 扣费原则

建议统一采用“两段式”：

### 阶段 A：通过合法性校验

如果校验失败：

- 不扣法术位
- 不扣体力
- 不扣数量
- 不扣充能
- 只给出失败原因

### 阶段 B：进入正式使用结算

一旦结算开始：

- 主成本默认视为已承诺
- 后续即使攻击未命中，也通常保留主要消耗

例如：

- 火球术施放出去但被躲开，法术位仍消耗
- 治疗药水已经喝下去但恢复量较低，药水仍消耗
- 拉弓射箭后未命中，箭矢默认已消耗

## 8.3 不同对象的默认消耗规则

### 法术

- 默认消耗法术位
- 部分法术还消耗专注位、体力或材料
- 失败或未命中不返还法术位

### 武装

- 默认不消耗武器本体
- 可消耗弹药、耐久、充能、附着效果次数
- 临时投掷物武器可消耗实例数量

### 道具

- 消耗品：扣数量
- 工具：默认扣耐久或次数，第一阶段可先不做耐久，只做次数/冷却
- 充能器具：扣充能
- 任务物：默认不允许随意消耗，除非定义中显式允许

## 9. 法术使用规则

## 9.1 法术分类

第一阶段法术至少分为：

- 戏法
- 有位法术
- 仪式法术
- 装备授予法术
- 卷轴/一次性法术

### 9.1.1 当前法术模板定义层 `SpellDefinition`

法术模板层建议直接对齐当前 `spell_definitions.csv` 的已有字段，
并补一个新的 `spell_cost` 字段用于表达法术的基础消耗。

建议结构：

```ts
type SpellDefinition = {
  definition_id: string;
  name: string;
  attack_mode: 'targeted_attack' | 'aoe_attack';
  casting_ability: 'intelligence' | 'wisdom' | 'charisma' | 'other';
  spell_cost: string;
  damage_dice: string;
  damage_bonus: number;
  damage_type: string;
  area_shape: 'none' | 'sphere' | 'cone' | 'line' | 'burst' | 'emanation';
  area_radius_m: number;
  area_length_m: number;
  self_target_policy: 'never' | 'can_include_self' | 'always_include_self';
  description: string;
  resolution_notes: string;
};
```

建议 `spell_definitions.csv` 表头扩展为：

```csv
definition_id,name,attack_mode,casting_ability,spell_cost,damage_dice,damage_bonus,damage_type,area_shape,area_radius_m,area_length_m,self_target_policy,description,resolution_notes
```

字段语义：

- `definition_id`
  - 稳定法术定义 ID。
- `name`
  - 玩家可见名称，不作为唯一识别键。
- `attack_mode`
  - 当前先支持：
    - `targeted_attack`
    - `aoe_attack`
- `casting_ability`
  - 模板层记录施法默认依赖的属性来源。
- `spell_cost`
  - 表示该法术的基础消耗。
  - 第一阶段先用单字段表达，避免过早拆成复杂资源对象。
  - 推荐值示例：
    - `cantrip`
    - `slot_1`
    - `slot_2`
    - `slot_3`
    - `special`
  - 含义是“按标准方式施放该法术时，默认要付出的主消耗”。
- `damage_dice`
  - 结构化伤害骰，例如 `1d10`、`8d6`。
  - 非伤害法术第一阶段允许为空。
- `damage_bonus`
  - 固定伤害加值。
- `damage_type`
  - 当前先保留字符串，兼容现有模板库与后续扩展。
- `area_shape`
  - 范围形状；`none` 表示不是范围法术。
- `area_radius_m`
  - 球形/爆发类半径，单位米。
- `area_length_m`
  - 线形/锥形/放射类长度，单位米。
- `self_target_policy`
  - 当前至少区分：
    - `never`
    - `can_include_self`
    - `always_include_self`
- `description`
  - 玩家可见的简要说明。
- `resolution_notes`
  - 给后端结算与 AI 叙事的补充说明。

## 9.2 法术授权规则

角色对一个法术可能有多种授权：

- `known`
- `prepared`
- `granted_by_item`
- `scroll_cast`
- `temporary_story_access`

第一阶段建议：

- 不强行实现完整 prepared 系统
- 但数据层要预留 `known` 与 `prepared` 的区分

## 9.3 法术成分规则

第一阶段建议支持简化版成分：

- `verbal`
- `somatic`
- `material`

后端要能判断：

- 沉默是否阻止 `verbal`
- 双手受限是否阻止 `somatic`
- 缺材料是否阻止 `material`

### 第一阶段默认简化

- 普通低价材料不逐件管理
- 昂贵材料或剧情材料才做真实库存校验

## 9.4 法术位规则

法术位消耗必须由后端结算，不由 AI 自由决定。AI 只能返回：

- 这次识别到的是哪一个法术
- 这次建议使用几环法术位

后端负责：

- 校验该法术位是否足够
- 实际扣除
- 更新当前法术位

### 9.4.1 法术资源状态建议

结合当前设计与 `spellwarartitemcostdesign.md`，法术正式资源应统一为“法术位”，
不再沿用旧的“法术值”口径。

建议角色侧最少保留：

```ts
type SpellSlotState = {
  level_1: number;
  level_2: number;
  level_3: number;
  level_4: number;
  level_5: number;
  level_6: number;
  level_7: number;
  level_8: number;
  level_9: number;
};

type SpellResourceState = {
  spell_slots_max: SpellSlotState;
  spell_slots_current: SpellSlotState;
  spell_slot_recover_per_public_turn?: number;
};
```

说明：

- `spell_slots_max`
  - 角色当前可持有的各环法术位上限。
- `spell_slots_current`
  - 角色当前剩余的各环法术位。
- `spell_slot_recover_per_public_turn`
  - 这是从 `spellwarartitemcostdesign.md` 并入的原型期扩展位；
  - 若项目继续采用“公开回合逐步恢复法术位”的方案，可用它表达恢复速度；
  - 若后续改回更接近 DND 的长休/短休恢复，则该字段可废弃或迁移。

当前口径：

- 法术基础消耗由 `SpellDefinition.spell_cost` 表达。
- 真正扣减哪个资源，由后端把 `spell_cost` 映射到 `spell_slots_current` 结算。
- 若是 `cantrip`，默认不扣法术位。

## 9.5 专注规则

建议第一阶段就把专注做成正式字段，但先支持最小闭环：

- 角色同一时间只能维持一个专注效果
- 新专注覆盖旧专注
- 受伤或特殊失败时可能掉专注

## 9.6 武技使用规则

武技与法术类似，都是“可声明、可校验、可消耗、可结算”的主动能力；
但它不应复用法术位，而应有独立资源口径。

### 9.6.1 武技定位

第一阶段建议把武技定义为：

- 近战/远程攻击强化
- 防御反制
- 位移压制
- 稳定站位或维持节奏的战斗技巧

当前代码层角色只正式保存：

- `skills_proficient`
- `skill_origins`

因此第一阶段可以先把武技挂在技能池里，
但设计文档层应提前预留独立的武技模板结构。

### 9.6.2 建议的武技模板定义层 `WarArtDefinition`

当前还没有正式的 `war_art_definitions.csv`，
这里先定义建议结构，后续若落地模板库可直接按这套字段开表。

```ts
type WarArtDefinition = {
  definition_id: string;
  name: string;
  attack_mode: 'none' | 'targeted_attack' | 'aoe_attack';
  scaling_ability: 'strength' | 'dexterity' | 'constitution' | 'other';
  martial_cost: number;
  cooldown_rounds: number;
  damage_dice: string;
  damage_bonus: number;
  damage_type: string;
  area_shape: 'none' | 'sphere' | 'cone' | 'line' | 'burst' | 'emanation';
  area_radius_m: number;
  area_length_m: number;
  self_target_policy: 'never' | 'can_include_self' | 'always_include_self';
  description: string;
  resolution_notes: string;
};
```

字段语义：

- `definition_id`
  - 稳定武技定义 ID。
- `name`
  - 武技显示名。
- `attack_mode`
  - 是否进入攻击结算，以及是单体还是范围型。
- `scaling_ability`
  - 主要受哪类体能属性驱动。
- `martial_cost`
  - 施放或发动一次武技默认消耗多少武技点。
- `cooldown_rounds`
  - 从 `spellwarartitemcostdesign.md` 并入的冷却制预留字段；
  - 若当前采用纯费用制，可默认 `0`；
  - 若个别武技同时需要冷却，则可写具体回合数。
- 其他字段
  - 与法术模板保持尽量一致，方便统一识别、统一结算与统一日志。

### 9.6.3 建议的武技资源状态 `WarArtResourceState`

结合 `spellwarartitemcostdesign.md`，武技资源更适合走“积累点数”而非法术位：

```ts
type WarArtResourceState = {
  martial_points_max: number;
  martial_points_current: number;
  gain_on_hit: number;
  gain_on_hurt: number;
  point_cap: number;
};
```

说明：

- `martial_points_max`
  - 当前角色理论可持有的武技点上限。
- `martial_points_current`
  - 当前剩余武技点。
- `gain_on_hit`
  - 命中后默认获得几点武技点。
- `gain_on_hurt`
  - 受伤后默认获得几点武技点。
- `point_cap`
  - 当前原型期建议最大上限；按 `spellwarartitemcostdesign.md` 先写到 `9`。

当前建议口径：

- 武技主资源不和法术位混用。
- 武技点主要通过战斗内命中、受伤、特殊武技效果获取。
- 若某个武技还要走冷却，则 `cooldown_rounds` 与武技点可以并存。
- 若角色升级系统后续落地，再决定武技点上限和获取效率如何成长。

## 10. 武装使用规则

## 10.1 武装不等于“只要在背包里就能用”

武装分成三类：

- 已装备武装
- 可快速取用武装
- 背包深处武装

默认规则：

- 已装备武装：可直接用于攻击/防御
- 快速取用武装：可在允许的动作代价下切换并使用
- 背包深处武装：不能无代价直接用于即时战斗或公开回合攻击

## 10.2 武装校验

至少检查：

- 对应实例是否存在
- 是否在合法装备槽
- 是否满足双手/副手要求
- 是否满足职业或熟练要求

### 熟练影响

第一阶段建议：

- 不熟练也允许使用
- 但给予明确惩罚### - 命中减值
  - 额外体力消耗
  - 更高失败风险

这样比“完全禁止使用”更适合原型期。

## 7. 武器设计

### 7.1 武器目标

武器不只影响战斗。

它同时影响：

- 主聊天公开动作的威慑感
- NPC 对玩家态度
- 遭遇中的威胁判断
- 战斗中的攻击与伤害
- 某些可交互物的处理方式

例如：

- 匕首可以割断绳索
- 长杆武器适合隔着障碍试探
- 火把可以点燃易燃物，也能临时提供照明

7.3 武器字段

```
type WeaponProfile = {
  weapon_class: 'light' | 'heavy' ;
  attack_ability: 'strength' | 'dexterity';
  damage_dice: string;
  damage_type: 'bludgeoning' | 'piercing' | 'slashing' | 'fire' | 'cold' | 'lightning' | 'poison' | 'psychic';
  attack_bonus_flat?: number;
  range_band?: 'engaged' | 'near' | 'far';
  handedness: 'one_hand' | 'two_hands' | 'off_hand_only';
  traits: string;
	description: string;
};
```

 traits: 用于表述这个武器的特性，好给予AI描写和给予BUFF的参考，BUFF还未设计占位。

武器描述需要给予这个武器的外观的描写，好给予AI描写的参考

### 7.4 武器表

- 武器表内需要支持所有以上字段，同时武器本身也是道具的一种，拥有道具的属性，普通武器，剧情关键武器。
- debug按钮调整一下，叫做武器表debug操作，点击后弹出窗口，可以清空武器表，也可以校验当前武器表武器每一列是否都有内容，然后就是武器填充，让玩家输入prompt和数量，然后AI返回格式填充武器表。
- 表格内容规则，字符必须是中文。

## 10.3 护甲与盾牌

护甲与盾牌默认不走“主动使用”按钮；它们更多是持续状态：

- 修改 AC / 防御能力
- 影响潜行/移动/体力消耗
- 影响公开行为中的威慑感

但装备/卸装本身要受校验和时间代价约束。

## 11. 道具使用规则

## 11.1 道具分类

建议至少分为：

- `consumable`
- `tool`
- `throwable`
- `medical`
- `quest`
- `material`
- `trinket`

## 11.2 道具默认使用模式

### 消耗品

- 直接扣数量
- 可无检定或触发检定

### 工具

- 默认不消失
- 可能扣次数、充能、时间或体力

### 投掷物

- 默认消耗实例或数量
- 可进入攻击结算

### 医疗物

- 可能接入濒死/稳定/治疗规则

### 任务物

- 默认禁止随意消耗
- 需要定义明确允许的使用场景

## 11.3 道具使用失败后的处理

默认规则：

- 若未通过合法性校验，不消耗
- 若已进入正式使用动作，通常扣除主消耗
- 特殊高价值剧情物可定义为“失败不消耗”

## 12. 模块联动规则

## 12.1 主聊天

主聊天中的法术、武装、道具声明，应先走统一识别与校验，再决定：

- 是普通检定
- 是公开回合声明
- 是场景物交互
- 是无效行为

主聊天不应绕过资源校验。

## 12.2 NPC 单聊

NPC 单聊中允许：

- 出示物品
- 递交道具
- 用武装威慑
- 施放定向法术

但仍要校验：

- 是否持有
- 是否装备
- 是否有法术位
- 是否被当前状态阻止

## 12.3 公开回合

公开回合中的攻击/物品使用，必须继续复用：

- 统一识别
- 统一合法性校验
- 统一消耗

然后再进入公开回合自己的：

- 互动
- 攻击回应
- 对抗
- 伤害结算

不能把公开回合变成另一套资源真相。

## 12.4 战斗

战斗模块对法术、武装、道具的使用，应严格依赖同一份“拥有权 + 资源可用性”。

战斗不单独发明：

- 第二份法术位
- 第二份装备状态
- 第二份背包数量

## 13. AI 与后端的职责分界

## 13.1 AI 负责什么

- 识别玩家想用的对象
- 从候选池选择定义 ID / 实例 ID
- 判断上下文中的目标与后果
- 生成叙事文本

## 13.2 后端负责什么

- 校验对象是否真实存在
- 校验角色是否有使用权
- 校验资源是否足够
- 校验当前状态是否允许
- 扣除费用
- 更新库存、法术位、体力、充能、状态

## 13.3 严格禁止的做法

- 前端靠字符串判断玩家是不是在用法术
- 后端靠字符串猜玩家背包里是不是有这件东西
- AI 不经后端校验直接改库存或法术位

## 14. 建议新增的数据设计方向

这部分是设计方向，不是本阶段必须一次性落地的最终 schema。

## 14.1 装备使用条目

建议显式记录：

- 当前装备槽位
- 是否可快速切换
- 是否需要双手
- 是否要求空手
- 是否消耗弹药

## 14.2 道具实例扩展

建议 `InventoryItem` 后续补充：

- `definition_id`
- `charge_current`
- `charge_max`
- `consumable_on_use`
- `requires_attunement`
- `equipped_slot`
- `origin_kind`
- `origin_ref`

## 14.3 统一使用成本对象

建议所有法术/武装/道具使用最终都能归一成：

- 使用对象
- 目标
- 前置校验结果
- 实际扣费项
- 实际效果
- 日志摘要

## 15. 前端交互设计

## 15.1 新游戏构筑

建议新增玩家初始构筑界面，而不是一上来就直接给一个全空角色面板。

构筑流程建议：

1. 选择职业/背景/基础模板
2. 分配属性
3. 选择起始法术
4. 选择起始武装与补给
5. 确认生成

## 15.2 使用失败反馈

使用失败时，前端不应只显示“失败”。

应明确告诉玩家是哪一类失败：

- 未持有
- 未装备
- 法术位不足
- 体力不足
- 数量不足
- 当前状态禁止
- 当前场景不可用

## 15.3 使用前提示

对于高成本行为，前端应明确展示预扣费信息：

- 将消耗几环法术位
- 将消耗多少体力
- 将消耗几件道具
- 将占用哪类动作

## 16. 第一阶段建议实现顺序

为了避免一次改太散，建议实现顺序固定为：

### P1：统一校验核

- 先做后端统一使用校验
- 接上主聊天 / 公开回合 / 战斗

### P2：玩家初始构筑

- 新增玩家建角与起始包生成
- 让法术/武装/道具有正式来源

### P3：统一消耗落盘

- 法术位
- 体力
- 物品数量
- 充能

### P4：高级规则

- 专注
- 成分
- 不熟练惩罚
- 休息恢复
- 高级装备/道具例外规则

## 17. 验收标准

满足以下条件，视为第一版设计可接受：

- 玩家创建新角色时，法术、武装、道具有明确初始来源。
- 玩家尝试使用法术、武装、道具时，后端一定会先做统一合法性校验。
- 校验失败不会误扣主要资源。
- 校验通过后，资源消耗与使用结果会真实写回存档。
- 主聊天、公开回合、NPC 单聊、战斗使用的是同一份资源真相。
- AI 不再直接决定“玩家默认会这个法术/拥有这件装备”。
- 前端能明确提示“不能使用”的具体原因。

## 18. 暂不纳入本草案

- 完整 5E 法术准备表
- 完整材料包与逐件材料经济
- 完整耐久系统
- 完整附魔/制作树
- 完整商店定价平衡
- 完整职业专长与多职业规则

## 19. 与现有文档的关系

这份草案审阅通过后，建议按以下方式并入口径：

- `roledesign.md`
  - 补“玩家初始构筑”章节
- `interactitemdesign.md`
  - 补“统一使用校验”和“消耗规则”章节
- `publicturninteractiondesign.md`
  - 补“公开回合攻击/施法前置合法性校验引用”
- `trash/battlesystem.md`
  - 该文档已弃用，仅保留历史归档；如未来恢复战斗设计，应新建文档重新定义口径
