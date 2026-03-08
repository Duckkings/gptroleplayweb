import { CharacterInventoryModal } from './CharacterInventoryModal';
import type { NpcRoleCard } from '../types/app';

type Props = {
  open: boolean;
  role: NpcRoleCard | null;
  busy?: boolean;
  onClose: () => void;
  onEquip: (itemId: string, slot: 'weapon' | 'armor') => void;
  onUnequip: (slot: 'weapon' | 'armor') => void;
  onInspect: (itemId: string, itemName: string) => void;
  onUse: (itemId: string, itemName: string) => void;
};

export function RoleInventoryModal({
  open,
  role,
  busy = false,
  onClose,
  onEquip,
  onUnequip,
  onInspect,
  onUse,
}: Props) {
  return (
    <CharacterInventoryModal
      open={open}
      ownerType="role"
      ownerId={role?.role_id}
      displayName={role?.name ?? ''}
      sheet={role?.profile.dnd5e_sheet ?? null}
      busy={busy}
      onClose={onClose}
      onEquip={onEquip}
      onUnequip={onUnequip}
      onInspect={onInspect}
      onUse={onUse}
    />
  );
}
