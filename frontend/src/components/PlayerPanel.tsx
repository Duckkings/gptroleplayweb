import { useEffect, useState } from 'react';
import type { InventoryItem, PlayerStaticData, RoleBuff } from '../types/app';

type Props = {
  open: boolean;
  value: PlayerStaticData;
  onClose: () => void;
  onSave: (next: PlayerStaticData) => void;
};

function parseLines(text: string): string[] {
  return text
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);
}

export function PlayerPanel({ open, value, onClose, onSave }: Props) {
  const [draft, setDraft] = useState<PlayerStaticData>(value);
  const [newItemName, setNewItemName] = useState('');
  const [newItemType, setNewItemType] = useState<'weapon' | 'armor' | 'misc'>('misc');
  const [newBuffName, setNewBuffName] = useState('');
  const [newBuffAc, setNewBuffAc] = useState(0);
  const [newBuffDc, setNewBuffDc] = useState(0);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  if (!open) return null;

  const sheet = draft.dnd5e_sheet;
  const setSheet = (next: PlayerStaticData['dnd5e_sheet']) => setDraft((prev) => ({ ...prev, dnd5e_sheet: next }));

  const addItem = () => {
    const name = newItemName.trim();
    if (!name) return;
    const item: InventoryItem = {
      item_id: `item_${Date.now()}`,
      name,
      item_type: newItemType,
      description: '',
      weight: 0,
      rarity: 'common',
      value: 0,
      effect: '',
      uses_max: null,
      uses_left: null,
      cooldown_min: 0,
      bound: false,
      quantity: 1,
      slot_type: newItemType,
      attack_bonus: 0,
      armor_bonus: 0,
    };
    setSheet({
      ...sheet,
      backpack: { ...sheet.backpack, items: [...sheet.backpack.items, item] },
    });
    setNewItemName('');
  };

  const addBuff = () => {
    const name = newBuffName.trim();
    if (!name) return;
    const buff: RoleBuff = {
      buff_id: `buff_${Date.now()}`,
      name,
      description: '',
      source: 'manual',
      duration_min: 30,
      remaining_min: 30,
      stackable: false,
      effect: {
        strength_delta: 0,
        dexterity_delta: 0,
        constitution_delta: 0,
        intelligence_delta: 0,
        wisdom_delta: 0,
        charisma_delta: 0,
        ac_delta: newBuffAc,
        dc_delta: newBuffDc,
        speed_ft_delta: 0,
        move_speed_mph_delta: 0,
        hp_max_delta: 0,
        stamina_max_delta: 0,
      },
    };
    setSheet({ ...sheet, buffs: [...sheet.buffs, buff] });
    setNewBuffName('');
    setNewBuffAc(0);
    setNewBuffDc(0);
  };

  return (
    <section className="player-panel card">
      <header className="chat-header">
        <div>
          <h2>玩家数据面板</h2>
          <p>完整角色核心数据编辑</p>
        </div>
        <button onClick={onClose}>关闭</button>
      </header>

      <div className="player-form">
        <label>
          玩家ID
          <input type="text" value={draft.player_id} onChange={(e) => setDraft((p) => ({ ...p, player_id: e.target.value }))} />
        </label>
        <label>
          玩家名称
          <input type="text" value={draft.name} onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))} />
        </label>
        <label>
          移动速度(m/h)
          <input type="number" min={1} value={draft.move_speed_mph} onChange={(e) => setDraft((p) => ({ ...p, move_speed_mph: Number(e.target.value) || 1 }))} />
        </label>
        <label>
          等级
          <input type="number" min={1} max={20} value={sheet.level} onChange={(e) => setSheet({ ...sheet, level: Number(e.target.value) || 1 })} />
        </label>
        <label>
          当前经验
          <input type="number" min={0} value={sheet.experience_current} onChange={(e) => setSheet({ ...sheet, experience_current: Math.max(0, Number(e.target.value) || 0) })} />
        </label>
        <label>
          升级所需经验
          <input type="number" min={0} value={sheet.experience_to_next_level} onChange={(e) => setSheet({ ...sheet, experience_to_next_level: Math.max(0, Number(e.target.value) || 0) })} />
        </label>
        <label>
          AC
          <input type="number" min={0} value={sheet.armor_class} onChange={(e) => setSheet({ ...sheet, armor_class: Math.max(0, Number(e.target.value) || 0) })} />
        </label>
        <label>
          DC
          <input type="number" min={0} value={sheet.difficulty_class} onChange={(e) => setSheet({ ...sheet, difficulty_class: Math.max(0, Number(e.target.value) || 0) })} />
        </label>
        <label>
          HP 当前
          <input type="number" min={0} value={sheet.hit_points.current} onChange={(e) => setSheet({ ...sheet, hit_points: { ...sheet.hit_points, current: Math.max(0, Number(e.target.value) || 0) } })} />
        </label>
        <label>
          HP 上限
          <input type="number" min={1} value={sheet.hit_points.maximum} onChange={(e) => setSheet({ ...sheet, hit_points: { ...sheet.hit_points, maximum: Math.max(1, Number(e.target.value) || 1) } })} />
        </label>
        <label>
          体力 当前
          <input type="number" min={0} value={sheet.stamina_current} onChange={(e) => setSheet({ ...sheet, stamina_current: Math.max(0, Number(e.target.value) || 0) })} />
        </label>
        <label>
          体力 上限
          <input type="number" min={1} value={sheet.stamina_maximum} onChange={(e) => setSheet({ ...sheet, stamina_maximum: Math.max(1, Number(e.target.value) || 1) })} />
        </label>
        <label>
          STR
          <input type="number" min={1} max={30} value={sheet.ability_scores.strength} onChange={(e) => setSheet({ ...sheet, ability_scores: { ...sheet.ability_scores, strength: Number(e.target.value) || 10 } })} />
        </label>
        <label>
          DEX
          <input type="number" min={1} max={30} value={sheet.ability_scores.dexterity} onChange={(e) => setSheet({ ...sheet, ability_scores: { ...sheet.ability_scores, dexterity: Number(e.target.value) || 10 } })} />
        </label>
        <label>
          CON
          <input type="number" min={1} max={30} value={sheet.ability_scores.constitution} onChange={(e) => setSheet({ ...sheet, ability_scores: { ...sheet.ability_scores, constitution: Number(e.target.value) || 10 } })} />
        </label>
        <label>
          INT
          <input type="number" min={1} max={30} value={sheet.ability_scores.intelligence} onChange={(e) => setSheet({ ...sheet, ability_scores: { ...sheet.ability_scores, intelligence: Number(e.target.value) || 10 } })} />
        </label>
        <label>
          WIS
          <input type="number" min={1} max={30} value={sheet.ability_scores.wisdom} onChange={(e) => setSheet({ ...sheet, ability_scores: { ...sheet.ability_scores, wisdom: Number(e.target.value) || 10 } })} />
        </label>
        <label>
          CHA
          <input type="number" min={1} max={30} value={sheet.ability_scores.charisma} onChange={(e) => setSheet({ ...sheet, ability_scores: { ...sheet.ability_scores, charisma: Number(e.target.value) || 10 } })} />
        </label>
        <label>
          金币
          <input type="number" min={0} value={sheet.backpack.gold} onChange={(e) => setSheet({ ...sheet, backpack: { ...sheet.backpack, gold: Math.max(0, Number(e.target.value) || 0) } })} />
        </label>
      </div>

      <div className="player-form">
        <label>
          技能（每行一个）
          <textarea value={sheet.skills_proficient.join('\n')} onChange={(e) => setSheet({ ...sheet, skills_proficient: parseLines(e.target.value) })} />
        </label>
        <label>
          法术（每行一个）
          <textarea value={sheet.spells.join('\n')} onChange={(e) => setSheet({ ...sheet, spells: parseLines(e.target.value) })} />
        </label>
      </div>

      <div className="player-form">
        <label>
          新增背包物品
          <input type="text" value={newItemName} onChange={(e) => setNewItemName(e.target.value)} placeholder="物品名称" />
        </label>
        <label>
          物品类型
          <select value={newItemType} onChange={(e) => setNewItemType(e.target.value as 'weapon' | 'armor' | 'misc')}>
            <option value="misc">misc</option>
            <option value="weapon">weapon</option>
            <option value="armor">armor</option>
          </select>
        </label>
        <button onClick={addItem}>添加物品</button>
        <p>当前物品：{sheet.backpack.items.map((i) => i.name).join(' / ') || '无'}</p>
      </div>

      <div className="player-form">
        <label>
          新增BUFF
          <input type="text" value={newBuffName} onChange={(e) => setNewBuffName(e.target.value)} placeholder="BUFF 名称" />
        </label>
        <label>
          AC加值
          <input type="number" value={newBuffAc} onChange={(e) => setNewBuffAc(Number(e.target.value) || 0)} />
        </label>
        <label>
          DC加值
          <input type="number" value={newBuffDc} onChange={(e) => setNewBuffDc(Number(e.target.value) || 0)} />
        </label>
        <button onClick={addBuff}>添加BUFF</button>
        <p>当前BUFF：{sheet.buffs.map((b) => b.name).join(' / ') || '无'}</p>
      </div>

      <div className="actions">
        <button onClick={() => onSave(draft)}>保存玩家数据</button>
      </div>
    </section>
  );
}
