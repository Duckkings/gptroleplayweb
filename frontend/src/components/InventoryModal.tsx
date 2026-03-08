import { CharacterInventoryModal } from './CharacterInventoryModal';
import type { PlayerStaticData } from '../types/app';

type Props = {
  open: boolean;
  player: PlayerStaticData;
  busy?: boolean;
  onClose: () => void;
  onEquip: (itemId: string, slot: 'weapon' | 'armor') => void;
  onUnequip: (slot: 'weapon' | 'armor') => void;
  onInspect: (itemId: string, itemName: string) => void;
  onUse: (itemId: string, itemName: string) => void;
};

export function InventoryModal({ open, player, busy = false, onClose, onEquip, onUnequip, onInspect, onUse }: Props) {
  return (
    <CharacterInventoryModal
      open={open}
      ownerType="player"
      ownerId={player.player_id}
      displayName={player.name}
      sheet={player.dnd5e_sheet}
      busy={busy}
      onClose={onClose}
      onEquip={onEquip}
      onUnequip={onUnequip}
      onInspect={onInspect}
      onUse={onUse}
    />
  );
}
