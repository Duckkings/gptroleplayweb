import tempfile
import unittest
from pathlib import Path

from app.core.storage import storage_state
from app.models.schemas import (
    InventoryItem,
    NpcRoleCard,
    PlayerStaticData,
    PlayerBuffAddRequest,
    PlayerEquipRequest,
    PlayerItemAddRequest,
    PlayerSpellSlotAdjustRequest,
    PlayerStaminaAdjustRequest,
    RoleBuff,
    RoleRelationSetRequest,
)
from app.services.world_service import (
    add_player_buff,
    add_player_item,
    clear_current_save,
    consume_spell_slots,
    consume_stamina,
    equip_player_item,
    get_current_save,
    recover_spell_slots,
    recover_stamina,
    set_role_relation,
)


class RoleSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))

    def tearDown(self) -> None:
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        self._tmpdir.cleanup()

    def test_item_equip_and_buff_recompute(self) -> None:
        sid = "sess_role_item"
        save = clear_current_save(sid)
        base_ac = save.player_static_data.dnd5e_sheet.armor_class

        updated = add_player_item(
            sid,
            PlayerItemAddRequest(
                item=InventoryItem(
                    item_id="sword_1",
                    name="短剑",
                    slot_type="weapon",
                    attack_bonus=2,
                )
            ),
        )
        self.assertEqual(len(updated.dnd5e_sheet.backpack.items), 1)

        updated = equip_player_item(sid, PlayerEquipRequest(item_id="sword_1", slot="weapon"))
        self.assertEqual(updated.dnd5e_sheet.equipment_slots.weapon_item_id, "sword_1")

        updated = add_player_buff(
            sid,
            PlayerBuffAddRequest(
                buff=RoleBuff(
                    buff_id="buff_ac",
                    name="护盾术",
                    effect={"ac_delta": 2, "dc_delta": 1},
                )
            ),
        )
        self.assertGreaterEqual(updated.dnd5e_sheet.armor_class, base_ac + 2)
        self.assertGreaterEqual(updated.dnd5e_sheet.difficulty_class, 1)

    def test_spell_slots_and_stamina_consume_recover(self) -> None:
        sid = "sess_role_resource"
        clear_current_save(sid)
        updated = consume_spell_slots(sid, PlayerSpellSlotAdjustRequest(level=1, amount=1))
        self.assertEqual(updated.dnd5e_sheet.spell_slots_current.level_1, 1)
        updated = recover_spell_slots(sid, PlayerSpellSlotAdjustRequest(level=1, amount=1))
        self.assertEqual(updated.dnd5e_sheet.spell_slots_current.level_1, 2)

        updated = consume_stamina(sid, PlayerStaminaAdjustRequest(amount=3))
        self.assertEqual(updated.dnd5e_sheet.stamina_current, 7)
        updated = recover_stamina(sid, PlayerStaminaAdjustRequest(amount=2))
        self.assertEqual(updated.dnd5e_sheet.stamina_current, 9)

    def test_set_role_relation(self) -> None:
        sid = "sess_role_relation"
        save = clear_current_save(sid)
        save.role_pool = [
            NpcRoleCard(
                role_id="npc_x",
                name="测试NPC",
                profile=PlayerStaticData(role_type="npc"),
            )
        ]
        from app.services.world_service import save_current

        save_current(save)

        updated = set_role_relation(
            sid,
            "npc_x",
            RoleRelationSetRequest(target_role_id="player_001", relation_tag="friendly", note="测试"),
        )
        self.assertEqual(updated.relations[-1].target_role_id, "player_001")
        self.assertEqual(updated.relations[-1].relation_tag, "friendly")
        persisted = get_current_save(sid)
        self.assertEqual(persisted.role_pool[0].relations[-1].relation_tag, "friendly")


if __name__ == "__main__":
    unittest.main()
