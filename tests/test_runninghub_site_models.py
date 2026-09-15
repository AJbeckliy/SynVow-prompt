from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import torch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "synvow_prompt_site_test"
if PACKAGE_NAME not in sys.modules:
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE_NAME] = package

utils = importlib.import_module(f"{PACKAGE_NAME}.utils")
product = importlib.import_module(f"{PACKAGE_NAME}.gpt_image2_product_studio_runninghub")


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class RunningHubSiteModelTests(unittest.TestCase):
    def setUp(self):
        utils.RUNNINGHUB_MODEL_CACHE.clear()

    def test_cn_and_ai_model_lists_use_separate_endpoints_and_caches(self):
        responses = {
            "https://llm.runninghub.cn/v1/models": ["qwen/qwen3.7-max", "glm-5.2"],
            "https://llm.runninghub.ai/v1/models": ["google/gemini-3.5-flash", "openai/gpt-5.5"],
        }

        def fake_get(url, timeout):
            return FakeResponse({
                "data": [
                    {
                        "id": item,
                        "capabilities": {
                            "vision": "gemini" in item or "qwen3.7-max" in item,
                        },
                    }
                    for item in responses[url]
                ]
            })

        with mock.patch.object(utils.requests, "get", side_effect=fake_get) as get:
            cn_models = utils.fetch_runninghub_models(site="cn")
            ai_models = utils.fetch_runninghub_models(site="ai")
            self.assertEqual(utils.fetch_runninghub_models(site="cn"), cn_models)
            self.assertEqual(
                utils.fetch_runninghub_models(site="ai", require_vision=True),
                ["google/gemini-3.5-flash"],
            )

        self.assertEqual(cn_models, responses["https://llm.runninghub.cn/v1/models"])
        self.assertEqual(ai_models, responses["https://llm.runninghub.ai/v1/models"])
        self.assertEqual(get.call_count, 2)

    def test_site_defaults_and_model_fallback_do_not_cross_regions(self):
        with mock.patch.object(
            utils,
            "fetch_runninghub_models",
            return_value=["deepseek/deepseek-v4-flash-vision-exp", "glm-5v-turbo"],
        ):
            model, changed = utils.resolve_runninghub_site_model(
                "cn",
                "google/gemini-3.5-flash",
                require_vision=True,
            )
        self.assertEqual(model, "deepseek/deepseek-v4-flash-vision-exp")
        self.assertTrue(changed)
        self.assertEqual(
            utils.runninghub_llm_site_from_url("https://www.runninghub.ai/openapi/v2"),
            utils.RUNNINGHUB_LLM_SITE_AI,
        )
        self.assertEqual(
            utils.default_runninghub_model(
                ["google/gemini-3.1-flash-lite-preview", "google/gemini-3.5-flash"],
                site="ai",
            ),
            "google/gemini-3.5-flash",
        )

    def test_missing_capability_metadata_uses_site_vision_fallback(self):
        response = FakeResponse({"data": [{"id": "unknown/text-model"}]})
        with mock.patch.object(utils.requests, "get", return_value=response):
            models = utils.fetch_runninghub_models(
                force=True,
                site="cn",
                require_vision=True,
            )
        self.assertEqual(models[0], "deepseek/deepseek-v4-flash-vision-exp")

    def test_llm_config_uses_selected_site_when_no_custom_url(self):
        with mock.patch.object(utils, "get_runninghub_api_key", return_value="test-key"):
            base_url, api_key, model = utils.resolve_llm_config(
                model_name="qwen/qwen3.7-max",
                site="cn",
            )
        self.assertEqual(base_url, "https://llm.runninghub.cn/v1/chat/completions")
        self.assertEqual(api_key, "test-key")
        self.assertEqual(model, "qwen/qwen3.7-max")

    def test_product_llm_request_uses_explicit_site_url_without_seed(self):
        response = FakeResponse({
            "choices": [{"message": {"content": "A" * 120}}],
        })
        image = torch.zeros((1, 32, 32, 3), dtype=torch.float32)
        with mock.patch.object(product.requests, "post", return_value=response) as post:
            result = product._enhance_prompt_with_llm(
                "test-key",
                "https://llm.runninghub.ai/v1/chat/completions",
                "google/gemini-3.5-flash",
                product.MODE_PRODUCT_REFINE,
                "base prompt",
                "",
                image,
            )

        self.assertEqual(result, "A" * 120)
        self.assertEqual(post.call_args.args[0], "https://llm.runninghub.ai/v1/chat/completions")
        self.assertNotIn("seed", post.call_args.kwargs["json"])

    def test_product_model_input_uses_cn_vision_default_and_union(self):
        cn_model = "deepseek/deepseek-v4-flash-vision-exp"
        ai_model = "google/gemini-3.5-flash"
        with (
            mock.patch.object(product, "runninghub_model_union", return_value=[cn_model, ai_model]) as union,
            mock.patch.object(product, "fetch_runninghub_models", return_value=[cn_model]) as fetch,
        ):
            values, options = product._llm_models_input()

        self.assertEqual(values, [cn_model, ai_model, "关闭"])
        self.assertEqual(options["default"], cn_model)
        union.assert_called_once_with(require_vision=True)
        fetch.assert_called_once_with(site="cn", require_vision=True)


if __name__ == "__main__":
    unittest.main()
