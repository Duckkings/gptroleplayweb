import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import ChatConfig, ChatRequest, Message
from app.services.ai_adapter import build_completion_options
from app.services.chat_service import chat_once


class ConfigModelsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_validate_config_migrates_legacy_payload(self) -> None:
        response = self.client.post(
            '/api/v1/config/validate',
            json={
                'version': '1.0.0',
                'openai_api_key': 'sk-test',
                'model': 'gpt-5',
                'stream': True,
                'temperature': 0.7,
                'max_tokens': 512,
                'gm_prompt': 'gm',
                'speech_time_per_50_tokens_min': 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['valid'])
        normalized = payload['normalized_config']
        self.assertEqual(normalized['provider'], 'openai')
        self.assertEqual(normalized['api_key'], 'sk-test')
        self.assertEqual(normalized['runtime']['temperature'], 0.7)
        self.assertEqual(normalized['runtime']['max_tokens'], 512)

    def test_validate_config_preserves_provider_specific_configs(self) -> None:
        response = self.client.post(
            '/api/v1/config/validate',
            json={
                'version': '2.0.0',
                'provider': 'gemini',
                'api_key': 'gemini-key',
                'base_url_override': '',
                'model': 'gemini-2.5-flash',
                'stream': True,
                'runtime': {},
                'provider_configs': {
                    'openai': {
                        'api_key': 'openai-key',
                        'base_url_override': '',
                        'model': 'gpt-5',
                        'runtime': {'temperature': 0.8, 'max_completion_tokens': 1200},
                    },
                    'deepseek': {
                        'api_key': 'deepseek-key',
                        'base_url_override': '',
                        'model': 'deepseek-chat',
                        'runtime': {'temperature': 0.7, 'max_tokens': 900},
                    },
                    'gemini': {
                        'api_key': 'gemini-key',
                        'base_url_override': '',
                        'model': 'gemini-2.5-flash',
                        'runtime': {},
                    },
                },
                'gm_prompt': 'gm',
                'speech_time_per_50_tokens_min': 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['valid'])
        normalized = payload['normalized_config']
        self.assertEqual(normalized['provider'], 'gemini')
        self.assertEqual(normalized['api_key'], 'gemini-key')
        self.assertEqual(normalized['provider_configs']['openai']['api_key'], 'openai-key')
        self.assertEqual(normalized['provider_configs']['deepseek']['model'], 'deepseek-chat')

    def test_model_profile_gpt5_prefers_max_completion_tokens(self) -> None:
        response = self.client.post(
            '/api/v1/config/models/profile',
            json={'provider': 'openai', 'model': 'gpt-5'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()['model']
        self.assertEqual(payload['capability_profile'], 'openai_gpt5')
        self.assertIn('max_completion_tokens', payload['supported_params'])
        self.assertNotIn('max_tokens', payload['supported_params'])

    def test_model_profile_gemini_uses_compat_profile(self) -> None:
        response = self.client.post(
            '/api/v1/config/models/profile',
            json={'provider': 'gemini', 'model': 'gemini-2.5-flash'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()['model']
        self.assertEqual(payload['capability_profile'], 'gemini_openai_compatible')
        self.assertEqual(payload['supported_params'], [])

    def test_model_discover_returns_normalized_profiles(self) -> None:
        fake_models = [SimpleNamespace(id='gpt-5'), SimpleNamespace(id='deepseek-chat')]
        fake_client = SimpleNamespace(models=SimpleNamespace(list=lambda: SimpleNamespace(data=fake_models)))
        with patch('app.services.ai_adapter.OpenAI', return_value=fake_client):
            response = self.client.post(
                '/api/v1/config/models/discover',
                json={'provider': 'openai', 'api_key': 'sk-test'},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()['models']
        self.assertEqual(payload[0]['id'], 'deepseek-chat')
        self.assertEqual(payload[1]['capability_profile'], 'openai_gpt5')


class ChatConfigAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_once_uses_max_completion_tokens_for_gpt5(self) -> None:
        captured: dict[str, object] = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
                choices=[SimpleNamespace(message=SimpleNamespace(content='ok', tool_calls=None))],
            )

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=fake_create))))
        with patch('app.services.chat_service.AsyncOpenAI', return_value=fake_client):
            payload = ChatRequest(
                session_id='sess_cfg_gpt5',
                config=ChatConfig(
                    provider='openai',
                    api_key='sk-test',
                    model='gpt-5',
                    stream=False,
                    runtime={'temperature': 0.6, 'max_completion_tokens': 640},
                    gm_prompt='gm',
                ),
                messages=[Message(role='user', content='hello')],
            )
            await chat_once(payload)

        self.assertEqual(captured['model'], 'gpt-5')
        self.assertEqual(captured['max_completion_tokens'], 640)
        self.assertNotIn('max_tokens', captured)

    def test_build_completion_options_omits_temperature_for_deepseek_reasoner(self) -> None:
        config = ChatConfig(
            provider='deepseek',
            api_key='sk-test',
            model='deepseek-reasoner',
            stream=False,
            runtime={'temperature': 0.9, 'max_tokens': 320},
            gm_prompt='gm',
        )
        options = build_completion_options(config)
        self.assertEqual(options['max_tokens'], 320)
        self.assertNotIn('temperature', options)

    def test_build_completion_options_omits_runtime_params_for_gemini(self) -> None:
        config = ChatConfig(
            provider='gemini',
            api_key='gemini-key',
            model='gemini-2.5-flash',
            stream=False,
            runtime={'temperature': 0.9, 'max_tokens': 320},
            gm_prompt='gm',
        )
        options = build_completion_options(config)
        self.assertEqual(options, {})


if __name__ == '__main__':
    unittest.main()
