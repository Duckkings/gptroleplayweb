import base64
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.core.storage import _save_bundle_dir, read_save_payload, storage_state, write_json_atomic
from app.main import app
from app.models.schemas import BuildMediaConfig, CharacterBuildBasicInfo, ChatConfig, Dnd5eAbilityScores, PortraitAssetRef, ProviderBuildMediaConfig, ProviderBuildMediaConfigMap
from app.services.character_build_prompt_presets import PORTRAIT_BASE_PROMPT, build_portrait_generation_prompt
from app.services.character_build_service import calculate_point_buy_cost, get_character_build_options
from app.services.character_media_service import resolve_effective_build_media_config
from app.services.world_service import clear_current_save, get_current_save


def _transparent_portrait_base64() -> str:
    image = Image.new("RGBA", (768, 1344), (0, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _media_config_payload() -> dict:
    config = ChatConfig(
        provider="openai",
        api_key="chat-key",
        model="gpt-5",
        stream=False,
        gm_prompt="gm",
        build_media=BuildMediaConfig(
            mode="explicit_provider",
            explicit_provider="openai",
            provider_configs=ProviderBuildMediaConfigMap(
                openai=ProviderBuildMediaConfig(
                    api_key="media-key",
                    generation_model="gpt-image-1",
                    background_removal_model="gpt-image-1",
                    vision_model="gpt-4.1-mini",
                )
            ),
        ),
    )
    return config.model_dump(mode="json")


class CharacterBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_save = storage_state.save_path
        self._orig_config = storage_state.config_path
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        storage_state.set_save_path(str(root / "current-save.json"))
        storage_state.set_config_path(str(root / "config.json"))
        self._require_user_patcher = patch("app.api.routes._require_user", return_value=None)
        self._require_user_patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._require_user_patcher.stop()
        storage_state.set_save_path(str(self._orig_save))
        storage_state.set_config_path(str(self._orig_config))
        self._tmpdir.cleanup()

    def test_legacy_save_migrates_character_build_state(self) -> None:
        save = clear_current_save("sess_legacy_build")
        payload = save.model_dump(mode="json")
        payload.pop("character_build_state", None)
        payload["player_static_data"]["name"] = "旧存档主角"
        shutil.rmtree(_save_bundle_dir(storage_state.save_path), ignore_errors=True)
        write_json_atomic(storage_state.save_path, payload)

        migrated = get_current_save("sess_legacy_build")

        self.assertEqual(migrated.character_build_state.player_status, "completed")

    def test_calculate_point_buy_cost_validates_range(self) -> None:
        scores = Dnd5eAbilityScores(strength=15, dexterity=14, constitution=13, intelligence=8, wisdom=10, charisma=12)
        self.assertEqual(calculate_point_buy_cost(scores), 27)
        with self.assertRaisesRegex(ValueError, "between 8 and 15"):
            calculate_point_buy_cost(Dnd5eAbilityScores(strength=16, dexterity=14, constitution=13, intelligence=8, wisdom=10, charisma=12))

    def test_build_portrait_generation_prompt_includes_basic_info_and_base_prompt(self) -> None:
        prompt = build_portrait_generation_prompt(
            "红发旅行法师，长杖，正立全身",
            CharacterBuildBasicInfo(name="Aria", age=22, race="elf", height_cm=172, body_type="athletic"),
        )

        self.assertIn("character basics:", prompt)
        self.assertIn("race: elf", prompt)
        self.assertIn("height_cm: 172", prompt)
        self.assertIn("红发旅行法师", prompt)
        self.assertIn(PORTRAIT_BASE_PROMPT, prompt)

    def test_gemini_media_defaults_use_image_and_segmentation_models(self) -> None:
        config = ChatConfig(
            provider="gemini",
            api_key="gemini-key",
            model="models/gemini-3-flash-preview",
            stream=False,
            gm_prompt="gm",
        )

        effective = resolve_effective_build_media_config(config)

        self.assertEqual(effective.provider, "gemini")
        self.assertEqual(effective.generation_model, "gemini-2.5-flash-image")
        self.assertEqual(effective.background_removal_model, "models/gemini-2.5-flash")
        self.assertEqual(effective.vision_model, "models/gemini-3-flash-preview")

    def test_generate_route_returns_composed_prompt_used(self) -> None:
        fake_asset = PortraitAssetRef(
            asset_id="portrait_fake",
            relative_path="build-temp/portrait_assets/portrait_fake.png",
            mime_type="image/png",
            width=768,
            height=1344,
            variant_kind="generated_raw",
            provider="openai",
            model="gpt-image-1",
        )
        with patch("app.api.routes.generate_portrait_assets", return_value=([fake_asset], "openai", "gpt-image-1")) as mock_generate:
            response = self.client.post(
                "/api/v1/character-build/media/generate",
                json={
                    "config": _media_config_payload(),
                    "prompt": "红发旅行法师，长杖，正立全身",
                    "basic_info": {"name": "Aria", "age": 22, "race": "elf", "height_cm": 172, "body_type": "athletic"},
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn(PORTRAIT_BASE_PROMPT, body["prompt_used"])
        self.assertIn("race: elf", body["prompt_used"])
        self.assertEqual(mock_generate.call_args.kwargs["prompt"], body["prompt_used"])

    def test_remove_background_route_returns_bg_removed_asset(self) -> None:
        upload_response = self.client.post(
            "/api/v1/character-build/media/upload",
            json={"data_base64": _transparent_portrait_base64(), "mime_type": "image/png"},
        )
        self.assertEqual(upload_response.status_code, 200, upload_response.text)
        raw_asset = upload_response.json()["asset"]

        remove_response = self.client.post(
            "/api/v1/character-build/media/remove-background",
            json={"config": _media_config_payload(), "raw_asset_id": raw_asset["asset_id"]},
        )
        self.assertEqual(remove_response.status_code, 200, remove_response.text)
        body = remove_response.json()
        self.assertEqual(body["raw_asset"]["variant_kind"], "uploaded_raw")
        self.assertEqual(body["bg_removed_asset"]["variant_kind"], "bg_removed")
        self.assertEqual(body["bg_removed_asset"]["derived_from_asset_id"], raw_asset["asset_id"])

    def test_finalize_route_accepts_raw_portrait_without_background_removal(self) -> None:
        upload_response = self.client.post(
            "/api/v1/character-build/media/upload",
            json={"data_base64": _transparent_portrait_base64(), "mime_type": "image/png"},
        )
        self.assertEqual(upload_response.status_code, 200, upload_response.text)
        raw_asset = upload_response.json()["asset"]

        finalize_response = self.client.post(
            "/api/v1/character-build/media/finalize",
            json={"asset_id": raw_asset["asset_id"]},
        )

        self.assertEqual(finalize_response.status_code, 200, finalize_response.text)
        body = finalize_response.json()
        self.assertEqual(body["asset"]["variant_kind"], "final_portrait")
        self.assertEqual(body["asset"]["derived_from_asset_id"], raw_asset["asset_id"])

    def test_describe_route_rejects_unconfirmed_portrait(self) -> None:
        upload_response = self.client.post(
            "/api/v1/character-build/media/upload",
            json={"data_base64": _transparent_portrait_base64(), "mime_type": "image/png"},
        )
        self.assertEqual(upload_response.status_code, 200, upload_response.text)
        raw_asset = upload_response.json()["asset"]

        describe_response = self.client.post(
            "/api/v1/character-build/media/describe",
            json={"config": _media_config_payload(), "asset_id": raw_asset["asset_id"]},
        )

        self.assertEqual(describe_response.status_code, 409, describe_response.text)
        self.assertIn("confirmed", describe_response.json()["detail"])

    def test_remove_background_route_surfaces_runtime_errors_as_502(self) -> None:
        upload_response = self.client.post(
            "/api/v1/character-build/media/upload",
            json={"data_base64": _transparent_portrait_base64(), "mime_type": "image/png"},
        )
        self.assertEqual(upload_response.status_code, 200, upload_response.text)
        raw_asset = upload_response.json()["asset"]

        with patch("app.api.routes.remove_portrait_background", side_effect=RuntimeError("boom")):
            remove_response = self.client.post(
                "/api/v1/character-build/media/remove-background",
                json={"config": _media_config_payload(), "raw_asset_id": raw_asset["asset_id"]},
            )

        self.assertEqual(remove_response.status_code, 502, remove_response.text)
        self.assertIn("boom", remove_response.json()["detail"])

    def test_player_complete_route_rejects_non_finalized_portrait(self) -> None:
        clear_current_save("sess_player_reject")
        upload_response = self.client.post(
            "/api/v1/character-build/media/upload",
            json={"data_base64": _transparent_portrait_base64(), "mime_type": "image/png"},
        )
        self.assertEqual(upload_response.status_code, 200, upload_response.text)
        raw_asset = upload_response.json()["asset"]

        complete_response = self.client.post(
            "/api/v1/character-build/player/complete",
            json={
                "session_id": "sess_player_reject",
                "basic_info": {"name": "主角", "age": 19, "race": "人类", "height_cm": 172, "body_type": "匀称"},
                "specialization": "warrior",
                "ability_scores": {
                    "strength": 15,
                    "dexterity": 13,
                    "constitution": 14,
                    "intelligence": 8,
                    "wisdom": 10,
                    "charisma": 12,
                },
                "final_portrait_asset_id": raw_asset["asset_id"],
                "appearance": "测试外貌",
                "loadout": {"spell_option_ids": [], "equipment_option_ids": [], "skill_option_ids": []},
            },
        )

        self.assertEqual(complete_response.status_code, 409, complete_response.text)
        self.assertIn("finalized portrait", complete_response.json()["detail"])

    def test_player_complete_route_marks_build_completed_and_writes_archive(self) -> None:
        clear_current_save("sess_player_complete")
        upload_response = self.client.post(
            "/api/v1/character-build/media/upload",
            json={"data_base64": _transparent_portrait_base64(), "mime_type": "image/png"},
        )
        raw_asset_id = upload_response.json()["asset"]["asset_id"]

        remove_response = self.client.post(
            "/api/v1/character-build/media/remove-background",
            json={"config": _media_config_payload(), "raw_asset_id": raw_asset_id},
        )
        bg_removed_asset_id = remove_response.json()["bg_removed_asset"]["asset_id"]

        finalize_response = self.client.post(
            "/api/v1/character-build/media/finalize",
            json={"asset_id": bg_removed_asset_id},
        )
        self.assertEqual(finalize_response.status_code, 200, finalize_response.text)
        final_asset_id = finalize_response.json()["asset"]["asset_id"]

        options = get_character_build_options("player", "warrior")
        complete_response = self.client.post(
            "/api/v1/character-build/player/complete",
            json={
                "session_id": "sess_player_complete",
                "basic_info": {"name": "艾琳", "age": 22, "race": "精灵", "height_cm": 168, "body_type": "高挑"},
                "specialization": "warrior",
                "ability_scores": {
                    "strength": 15,
                    "dexterity": 13,
                    "constitution": 14,
                    "intelligence": 8,
                    "wisdom": 10,
                    "charisma": 12,
                },
                "final_portrait_asset_id": final_asset_id,
                "appearance": "红发、轻甲法袍、持杖。",
                "loadout": {
                    "spell_option_ids": [item.option_id for item in options.spell_options[:2]],
                    "equipment_option_ids": [item.option_id for item in options.equipment_options[:2]],
                    "skill_option_ids": [item.option_id for item in options.skill_options[:2]],
                },
            },
        )
        self.assertEqual(complete_response.status_code, 200, complete_response.text)
        body = complete_response.json()
        self.assertEqual(body["state"]["player_status"], "completed")
        self.assertTrue(body["archive_id"])

        stored = get_current_save("sess_player_complete")
        self.assertEqual(stored.character_build_state.player_status, "completed")
        self.assertEqual(stored.player_static_data.build_archive_id, body["archive_id"])
        self.assertEqual(stored.player_static_data.portrait.variant_kind, "final_portrait")

        archive_dir = storage_state.save_path.parent / "player-builds" / body["archive_id"]
        self.assertTrue((archive_dir / "manifest.json").exists())
        self.assertTrue((archive_dir / "portrait.png").exists())

        persisted = read_save_payload(storage_state.save_path)
        assert persisted is not None
        self.assertEqual(persisted["character_build_state"]["player_status"], "completed")


if __name__ == "__main__":
    unittest.main()
