import json
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import torch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "synvow_prompt_transparent_test"
if PACKAGE_NAME not in sys.modules:
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE_NAME] = package

generator = importlib.import_module(f"{PACKAGE_NAME}.transparent_asset_generator")


class TransparentAssetLayerCountTests(unittest.TestCase):
    @mock.patch.object(generator, "resolve_llm_config")
    @mock.patch.object(generator.requests, "post")
    def test_runninghub_planner_uses_selected_site_chat_endpoint(self, post, resolve_config):
        resolve_config.return_value = (
            "https://llm.runninghub.ai/v1/chat/completions",
            "test-key",
            "google/gemini-3.5-flash",
        )
        response = mock.Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": "{\"slots\": []}"}}],
        }
        post.return_value = response

        result = generator._runninghub_chat_completion(
            "google/gemini-3.5-flash",
            "system",
            "user",
            llm_site="国际站 (.ai)",
        )

        self.assertEqual(result, '{"slots": []}')
        self.assertEqual(post.call_args.args[0], "https://llm.runninghub.ai/v1/chat/completions")
        resolve_config.assert_called_once_with(
            None,
            model_name="google/gemini-3.5-flash",
            site="国际站 (.ai)",
        )

    @mock.patch.object(
        generator,
        "fetch_runninghub_models",
        return_value=["deepseek/deepseek-v4-flash-vision-exp"],
    )
    @mock.patch.object(
        generator,
        "runninghub_model_union",
        return_value=["deepseek/deepseek-v4-flash-vision-exp"],
    )
    def test_layer_count_input_defaults_to_four(self, _union, _fetch):
        inputs = generator.SynVowTransparentAssetPromptGenerator.INPUT_TYPES()
        layer_input = inputs["required"]["layer_count"]
        self.assertEqual(layer_input[0], ["2", "3", "4", "5", "6"])
        self.assertEqual(layer_input[1]["default"], "4")
        self.assertIn("llm_site", inputs["optional"])
        self.assertIn("model", inputs["required"])

    def test_geometry_planner_prefers_flash_model(self):
        models = ["google/gemini-3.1-pro-preview", "google/gemini-3.5-flash"]
        self.assertEqual(generator._default_planner_model(models), "google/gemini-3.5-flash")

    @mock.patch.object(generator, "image_to_data_urls", return_value=["https://example.test/source.png"])
    @mock.patch.object(generator, "resolve_runninghub_site_model", return_value=("mock-model", False))
    @mock.patch.object(generator, "_runninghub_chat_completion")
    def test_split_auto_mode_sends_structured_geometry_to_llm(self, chat_completion, _resolve_model, _image_to_data_urls):
        chat_completion.return_value = json.dumps({
            "source_image_description": "visible source",
            "source_canvas": {
                "width": 482,
                "height": 907,
                "aspect_ratio": "482:907",
                "coordinate_system": "normalized_top_left_origin",
            },
            "style_prompt": "",
            "slots": [
                {
                    "slot_id": "background",
                    "name": "背景层",
                    "description": "背景",
                    "prompt": "background only",
                    "geometry": {
                        "layer_bbox_normalized": [0, 0, 1, 1],
                        "center_normalized": [0.5, 0.5],
                        "size_normalized": [1, 1],
                        "touches_edges": ["left", "right", "top", "bottom"],
                        "regions": [],
                    },
                },
                {
                    "slot_id": "subject_product",
                    "name": "主体/人物/产品层",
                    "description": "主体产品",
                    "visible_content": "robot vacuum",
                    "edit_instruction": "Extract only the robot vacuum.",
                    "geometry": {
                        "layer_bbox_normalized": [0.1, 0.3, 0.9, 0.95],
                        "regions": [
                            {"label": "product", "bbox_normalized": [0.2, 0.4, 0.8, 0.8]},
                            {"label": "hand", "bbox_normalized": [0.1, 0.1, 0.7, 0.5]},
                            {"label": "person", "bbox_normalized": [0.5, 0.2, 0.8, 0.7]},
                        ],
                    },
                },
                {
                    "slot_id": "text_logo",
                    "name": "文字/Logo层",
                    "description": "文字",
                    "prompt": "text and logo only",
                    "geometry": {
                        "layer_bbox_normalized": [0.2, 0.04, 0.8, 0.24],
                        "regions": [{"label": "headline", "bbox_normalized": [0.2, 0.04, 0.8, 0.14]}],
                    },
                },
            ],
        }, ensure_ascii=False)
        reference = torch.zeros((1, 907, 482, 3), dtype=torch.float32)
        result = generator.SynVowTransparentAssetPromptGenerator().generate(
            scene_preset="参考图分层拆图",
            planner_mode="自动规划(LLM)",
            asset_count="12",
            layer_count="3",
            custom_prompt="只拆图中真实存在的内容",
            model="mock-model",
            seed=1,
            product_or_reference_image=reference,
        )

        plan = json.loads(result[1])
        llm_payload = json.loads(chat_completion.call_args.args[2])
        self.assertEqual(len(result[0]), 3)
        self.assertEqual(plan["plan_source"], "llm:国内站 (.cn):mock-model")
        self.assertEqual(plan["layer_count"], 3)
        self.assertIsNone(plan["asset_count"])
        self.assertEqual(llm_payload["layer_count"], 3)
        self.assertEqual(llm_payload["source_canvas"]["width"], 482)
        self.assertEqual(llm_payload["source_canvas"]["height"], 907)
        self.assertEqual(
            [slot["slot_id"] for slot in llm_payload["slots"]],
            ["background", "subject_product", "text_logo"],
        )
        self.assertNotIn("asset_count", llm_payload)
        self.assertEqual(plan["source_canvas"]["aspect_ratio"], "482:907")
        self.assertEqual(plan["items"][1]["geometry"]["regions"][0]["label"], "product")
        self.assertIn("bbox=[0.1,0.3,0.9,0.95]", result[0][1])
        self.assertIn("hand[0.1,0.1,0.7,0.5]", result[0][1])
        self.assertIn("person[0.5,0.2,0.8,0.7]", result[0][1])
        self.assertIn("Edit the input image in place.", result[0][1])
        self.assertNotIn("Reference layer split mode.", result[0][1])
        self.assertTrue(all(200 <= len(prompt) <= 500 for prompt in result[0]))
        self.assertEqual(chat_completion.call_args.kwargs["llm_site"], "国内站 (.cn)")
        chat_completion.assert_called_once()

    @mock.patch.object(generator, "image_to_data_urls", return_value=["https://example.test/source.png"])
    @mock.patch.object(generator, "resolve_runninghub_site_model", return_value=("mock-model", False))
    @mock.patch.object(generator, "_runninghub_chat_completion")
    def test_split_mode_ignores_style_reference_image(self, chat_completion, _resolve_model, image_to_data_urls):
        chat_completion.return_value = json.dumps({
            "source_image_description": "visible source",
            "slots": [
                {
                    "slot_id": "background",
                    "visible_content": "background",
                    "bbox_normalized": [0, 0, 1, 1],
                    "regions": [],
                },
                {
                    "slot_id": "subject_product",
                    "visible_content": "subject",
                    "bbox_normalized": [0.2, 0.2, 0.8, 0.8],
                    "regions": [],
                },
            ],
        })
        reference = torch.zeros((1, 100, 80, 3), dtype=torch.float32)
        result = generator.SynVowTransparentAssetPromptGenerator().generate(
            scene_preset="参考图分层拆图",
            planner_mode="自动规划(LLM)",
            asset_count="2",
            layer_count="2",
            custom_prompt="",
            model="mock-model",
            seed=1,
            product_or_reference_image=reference,
            style_reference_image=reference,
        )

        plan = json.loads(result[1])
        image_to_data_urls.assert_called_once_with(reference)
        self.assertFalse(plan["style_reference_image_used"])
        self.assertEqual(plan["style_prompt_source"], "none_for_reference_layer_split")

    @mock.patch.object(generator, "_runninghub_chat_completion")
    def test_split_rule_mode_uses_layer_count_without_llm(self, chat_completion):
        result = generator.SynVowTransparentAssetPromptGenerator().generate(
            scene_preset="参考图分层拆图",
            planner_mode="规则预设(不调用LLM)",
            asset_count="12",
            layer_count="3",
            custom_prompt="",
            model="mock-model",
            seed=1,
        )
        plan = json.loads(result[1])
        self.assertEqual(plan["plan_source"], "layer_preset")
        self.assertEqual([item["name"] for item in plan["items"]], ["背景层", "主体/人物/产品层", "文字/Logo层"])
        chat_completion.assert_not_called()

    def test_layer_counts_use_prefix_of_fixed_six_slots(self):
        full_names = [slot["name"] for slot in generator.LAYOUT_SPLIT_SLOTS]
        self.assertEqual(full_names, [
            "背景层",
            "主体/人物/产品层",
            "文字/Logo层",
            "装饰元素层",
            "光影氛围层",
            "其他可复用元素层",
        ])
        for count in range(2, 7):
            items = generator._layout_split_fallback_items(count)
            self.assertEqual([item["name"] for item in items], full_names[:count])

    def test_duplicate_llm_slots_cannot_duplicate_final_layers(self):
        repeated = {
            "slots": [
                {"slot_id": "text_logo", "name": "文字/Logo层", "visible_content": "headline"},
                {"slot_id": "text_logo", "name": "文字/Logo层", "visible_content": "headline"},
                {"slot_id": "text_logo", "name": "文字/Logo层", "visible_content": "headline"},
                {"slot_id": "text_logo", "name": "文字/Logo层", "visible_content": "headline"},
            ]
        }
        items = generator._normalize_layout_split_slots(repeated, 4)
        self.assertEqual(
            [item["slot_id"] for item in items],
            ["background", "subject_product", "text_logo", "decorations"],
        )
        self.assertEqual([item["name"] for item in items].count("文字/Logo层"), 1)

    def test_five_layers_separate_decoration_and_light_effects(self):
        items = generator._layout_split_fallback_items(5)
        prompts = {item["name"]: item["prompt"] for item in items}
        self.assertIn("separately requested light/atmosphere layer", prompts["装饰元素层"])
        self.assertIn("atmospheric overlay effects", prompts["光影氛围层"])


if __name__ == "__main__":
    unittest.main()
