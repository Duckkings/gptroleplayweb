import type { Dnd5eCharacterSheet } from '../types/app';

type Props = {
  open: boolean;
  ownerType: 'player' | 'role';
  ownerId?: string;
  displayName: string;
  sheet: Dnd5eCharacterSheet | null;
  busy?: boolean;
  onClose: () => void;
  onEquip: (itemId: string, slot: 'weapon' | 'armor') => void;
  onUnequip: (slot: 'weapon' | 'armor') => void;
  onInspect: (itemId: string, itemName: string) => void;
  onUse: (itemId: string, itemName: string) => void;
};

export function CharacterInventoryModal({
  open,
  ownerType,
  ownerId,
  displayName,
  sheet,
  busy = false,
  onClose,
  onEquip,
  onUnequip,
  onInspect,
  onUse,
}: Props) {
  if (!open || !sheet) return null;

  const backpack = sheet.backpack;
  const equipment = sheet.equipment_slots;
  const weaponItem = backpack.items.find((item) => item.item_id === equipment.weapon_item_id) ?? null;
  const armorItem = backpack.items.find((item) => item.item_id === equipment.armor_item_id) ?? null;

  return (
    <div className="modal-mask">
      <div className="modal-card modal-wide inventory-modal-card">
        <header className="inventory-modal-header">
          <div>
            <h3>{ownerType === 'player' ? '玩家背包' : '队友背包'}</h3>
            <p>
              {displayName}
              {ownerId ? ` | ${ownerId}` : ''}
            </p>
            <p>
              武器: {weaponItem?.name ?? '未装备'} | 护甲: {armorItem?.name ?? '未装备'}
            </p>
          </div>
          <button onClick={onClose}>关闭</button>
        </header>

        <div className="inventory-summary">
          <div className="inventory-summary-card">
            <strong>金币</strong>
            <p>{backpack.gold}</p>
          </div>
          <div className="inventory-summary-card">
            <strong>物品数量</strong>
            <p>{backpack.items.length}</p>
          </div>
          <div className="inventory-summary-card">
            <strong>职业/种族</strong>
            <p>
              {sheet.char_class || '-'} / {sheet.race || '-'}
            </p>
          </div>
        </div>

        <section className="inventory-list">
          {backpack.items.length === 0 && <p className="hint">当前背包为空。</p>}
          {backpack.items.map((item) => {
            const isWeaponEquipped = equipment.weapon_item_id === item.item_id;
            const isArmorEquipped = equipment.armor_item_id === item.item_id;
            const isEquipped = isWeaponEquipped || isArmorEquipped;
            return (
              <article key={item.item_id} className="inventory-item-card">
                <div className="inventory-item-head">
                  <strong>{item.name}</strong>
                  <small>
                    {item.item_type} | {item.rarity}
                  </small>
                </div>
                <p>{item.description || '暂无描述'}</p>
                <div className="inventory-item-meta">
                  <span>数量: {item.quantity}</span>
                  <span>价值: {item.value}</span>
                  <span>重量: {item.weight}</span>
                  <span>槽位: {item.slot_type}</span>
                </div>
                {(item.attack_bonus !== 0 || item.armor_bonus !== 0) && (
                  <div className="inventory-item-meta">
                    <span>攻击加值: {item.attack_bonus}</span>
                    <span>护甲加值: {item.armor_bonus}</span>
                  </div>
                )}
                {(item.uses_max !== null || item.uses_left !== null) && (
                  <div className="inventory-item-meta">
                    <span>剩余次数: {item.uses_left ?? '-'}</span>
                    <span>最大次数: {item.uses_max ?? '-'}</span>
                    <span>冷却: {item.cooldown_min} 分钟</span>
                  </div>
                )}
                {item.effect && <small className="inventory-item-effect">效果: {item.effect}</small>}
                {isEquipped && <p className="inventory-item-equipped">当前已装备</p>}
                <div className="inventory-item-actions">
                  {(item.slot_type === 'weapon' || item.slot_type === 'armor') && (
                    <button
                      onClick={() =>
                        isEquipped
                          ? onUnequip(item.slot_type === 'weapon' ? 'weapon' : 'armor')
                          : onEquip(item.item_id, item.slot_type === 'weapon' ? 'weapon' : 'armor')
                      }
                      disabled={busy}
                    >
                      {isEquipped ? '卸下' : '装备'}
                    </button>
                  )}
                  {item.slot_type === 'misc' && (
                    <button onClick={() => onUse(item.item_id, item.name)} disabled={busy || item.uses_left === 0}>
                      使用
                    </button>
                  )}
                  <button onClick={() => onInspect(item.item_id, item.name)} disabled={busy}>
                    观察
                  </button>
                </div>
              </article>
            );
          })}
        </section>
      </div>
    </div>
  );
}
