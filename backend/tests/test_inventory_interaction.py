import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.storage import storage_state
from app.models.schemas import (
    ActionCheckResponse,
    InventoryEquipRequest,
    InventoryInteractRequest,
    InventoryItem,
    InventoryOwnerRef,
    InventoryUnequipRequest,
    NpcRoleCard,
)
from app.services.world_service import (
    _build_npc_profile,
    clear_current_save,
    get_current_save,
    inventory_equip,
    inventory_interact,
    inventory_unequip,
    save_current,
)


class InventoryInteractionTests(unittest.TestCase):
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

    def _seed_save(self, session_id: str) -> None:
        save = clear_current_save(session_id)
        save.player_static_data.dnd5e_sheet.backpack.items = [
            InventoryItem(item_id="player_sword", name="短剑", slot_type="weapon", attack_bonus=2),
            InventoryItem(item_id="player_armor", name="皮甲", slot_type="armor", armor_bonus=2),
            InventoryItem(item_id="player_potion", name="治疗药剂", slot_type="misc", uses_max=2, uses_left=2, effect="回复少量生命值"),
        ]
        role_profile = _build_npc_profile("npc_inv", "Inventory NPC")
        role_profile.dnd5e_sheet.backpack.items.append(
            InventoryItem(item_id="npc_potion", name="队友药剂", slot_type="misc", uses_max=1, uses_left=1, effect="回复少量生命值")
        )
        role = NpcRoleCard(
            role_id="npc_inv",
            name="Inventory NPC",
            profile=role_profile,
        )
        save.role_pool = [role]
        save_current(save)

    def test_player_inventory_equip_and_unequip_generic(self) -> None:
        sid = "sess_inventory_player"
        self._seed_save(sid)

        equipped = inventory_equip(
            InventoryEquipRequest(
                session_id=sid,
                owner=InventoryOwnerRef(owner_type="player"),
                item_id="player_sword",
                slot="weapon",
            )
        )
        self.assertEqual(equipped.player.dnd5e_sheet.equipment_slots.weapon_item_id, "player_sword")

        unequipped = inventory_unequip(
            InventoryUnequipRequest(
                session_id=sid,
                owner=InventoryOwnerRef(owner_type="player"),
                slot="weapon",
            )
        )
        self.assertIsNone(unequipped.player.dnd5e_sheet.equipment_slots.weapon_item_id)

    def test_role_inventory_equip_and_unequip_generic(self) -> None:
        sid = "sess_inventory_role"
        self._seed_save(sid)
        save = get_current_save(sid)
        role = save.role_pool[0]
        role.profile.dnd5e_sheet.equipment_slots.weapon_item_id = None
        save_current(save)

        equipped = inventory_equip(
            InventoryEquipRequest(
                session_id=sid,
                owner=InventoryOwnerRef(owner_type="role", role_id="npc_inv"),
                item_id=role.profile.dnd5e_sheet.backpack.items[0].item_id,
                slot="weapon",
            )
        )
        self.assertIsNotNone(equipped.role)
        self.assertEqual(equipped.role.profile.dnd5e_sheet.equipment_slots.weapon_item_id, role.profile.dnd5e_sheet.backpack.items[0].item_id)

        unequipped = inventory_unequip(
            InventoryUnequipRequest(
                session_id=sid,
                owner=InventoryOwnerRef(owner_type="role", role_id="npc_inv"),
                slot="weapon",
            )
        )
        self.assertIsNotNone(unequipped.role)
        self.assertIsNone(unequipped.role.profile.dnd5e_sheet.equipment_slots.weapon_item_id)

    def test_inventory_equip_slot_mismatch_raises(self) -> None:
        sid = "sess_inventory_mismatch"
        self._seed_save(sid)

        with self.assertRaises(ValueError):
            inventory_equip(
                InventoryEquipRequest(
                    session_id=sid,
                    owner=InventoryOwnerRef(owner_type="player"),
                    item_id="player_potion",
                    slot="weapon",
                )
            )

    def test_inventory_inspect_does_not_consume_item_or_call_action_check(self) -> None:
        sid = "sess_inventory_inspect"
        self._seed_save(sid)

        with patch("app.services.world_service.action_check") as mocked_check:
            response = inventory_interact(
                InventoryInteractRequest(
                    session_id=sid,
                    owner=InventoryOwnerRef(owner_type="player"),
                    item_id="player_potion",
                    mode="inspect",
                    prompt="看看瓶身标签",
                )
            )
        mocked_check.assert_not_called()
        self.assertIsNone(response.action_check)
        updated = get_current_save(sid)
        item = next(entry for entry in updated.player_static_data.dnd5e_sheet.backpack.items if entry.item_id == "player_potion")
        self.assertEqual(item.uses_left, 2)

    def test_role_inventory_use_routes_actor_and_persists_uses(self) -> None:
        sid = "sess_inventory_role_use"
        self._seed_save(sid)
        captured: dict[str, str] = {}

        def fake_action_check(req):
            captured["actor_role_id"] = req.actor_role_id or ""
            return ActionCheckResponse(
                session_id=req.session_id,
                actor_role_id=req.actor_role_id or "",
                actor_name="Inventory NPC",
                actor_kind="npc",
                action_type="item_use",
                requires_check=True,
                ability_used="wisdom",
                ability_modifier=2,
                dc=10,
                check_task="让药剂顺利生效",
                dice_roll=18,
                total_score=20,
                success=True,
                critical="none",
                time_spent_min=3,
                narrative="队友顺利使用了物品。",
                applied_effects=[],
                relation_tag_suggestion=None,
            )

        with patch("app.services.world_service.action_check", side_effect=fake_action_check):
            response = inventory_interact(
                InventoryInteractRequest(
                    session_id=sid,
                    owner=InventoryOwnerRef(owner_type="role", role_id="npc_inv"),
                    item_id="npc_potion",
                    mode="use",
                    prompt="让他立刻喝下去",
                )
            )

        self.assertEqual(captured["actor_role_id"], "npc_inv")
        self.assertIsNotNone(response.action_check)
        self.assertEqual(response.action_check.actor_role_id, "npc_inv")
        updated = get_current_save(sid)
        role = next(item for item in updated.role_pool if item.role_id == "npc_inv")
        item = next(entry for entry in role.profile.dnd5e_sheet.backpack.items if entry.item_id == "npc_potion")
        self.assertEqual(item.uses_left, 0)

    def test_inventory_use_depleted_item_raises(self) -> None:
        sid = "sess_inventory_depleted"
        self._seed_save(sid)
        save = get_current_save(sid)
        item = next(entry for entry in save.player_static_data.dnd5e_sheet.backpack.items if entry.item_id == "player_potion")
        item.uses_left = 0
        save_current(save)

        with self.assertRaises(ValueError):
            inventory_interact(
                InventoryInteractRequest(
                    session_id=sid,
                    owner=InventoryOwnerRef(owner_type="player"),
                    item_id="player_potion",
                    mode="use",
                    prompt="直接喝掉",
                )
            )


if __name__ == "__main__":
    unittest.main()
