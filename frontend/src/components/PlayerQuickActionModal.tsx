import type { PlayerStaticData } from '../types/app';

export type PlayerQuickActionMode = 'root' | 'spell' | 'war_art';

type Props = {
  open: boolean;
  mode: PlayerQuickActionMode;
  player: PlayerStaticData;
  onClose: () => void;
  onBack: () => void;
  onOpenInventory: () => void;
  onShowSpells: () => void;
  onShowWarArts: () => void;
  onSelectSpell: (name: string) => void;
  onSelectWarArt: (name: string) => void;
};

function sumSpellSlots(slots: PlayerStaticData['dnd5e_sheet']['spell_slots_current']): number {
  return Object.values(slots).reduce((sum, value) => sum + Number(value || 0), 0);
}

export function PlayerQuickActionModal({
  open,
  mode,
  player,
  onClose,
  onBack,
  onOpenInventory,
  onShowSpells,
  onShowWarArts,
  onSelectSpell,
  onSelectWarArt,
}: Props) {
  if (!open) return null;

  const sheet = player.dnd5e_sheet;
  const spells = sheet.spells ?? [];
  const warArts = sheet.war_arts ?? [];
  const spellSlotsCurrent = sumSpellSlots(sheet.spell_slots_current);
  const spellSlotsMax = sumSpellSlots(sheet.spell_slots_max);

  return (
    <div className="modal-mask">
      <div className="modal-card player-quick-action-modal">
        <header className="player-quick-action-header">
          <div>
            <h3>{mode === 'root' ? '玩家快捷操作' : mode === 'spell' ? '选择法术' : '选择武技'}</h3>
            <p>
              {player.name} | HP {sheet.hit_points.current}/{sheet.hit_points.maximum} | 法 {spellSlotsCurrent}/{spellSlotsMax} | 武{' '}
              {sheet.martial_points_current}/{sheet.martial_points_maximum}
            </p>
          </div>
          <div className="actions">
            {mode !== 'root' && (
              <button type="button" onClick={onBack}>
                返回
              </button>
            )}
            <button type="button" onClick={onClose}>
              关闭
            </button>
          </div>
        </header>

        {mode === 'root' ? (
          <div className="player-quick-action-list">
            <button type="button" onClick={onOpenInventory}>
              打开背包
            </button>
            <button type="button" onClick={onShowSpells} disabled={spells.length === 0}>
              使用法术
            </button>
            <button type="button" onClick={onShowWarArts} disabled={warArts.length === 0}>
              使用武技
            </button>
            {spells.length === 0 && <p className="hint">当前未学会法术。</p>}
            {warArts.length === 0 && <p className="hint">当前未学会武技。</p>}
          </div>
        ) : (
          <div className="player-quick-action-list">
            {(mode === 'spell' ? spells : warArts).length === 0 && (
              <p className="hint">{mode === 'spell' ? '当前未学会法术。' : '当前未学会武技。'}</p>
            )}
            {(mode === 'spell' ? spells : warArts).map((item) => (
              <button
                key={`${mode}_${item}`}
                type="button"
                onClick={() => (mode === 'spell' ? onSelectSpell(item) : onSelectWarArt(item))}
              >
                {item}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
