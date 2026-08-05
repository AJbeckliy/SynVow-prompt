"""Offline checks for the standalone RunningHub H3 prompt-director node."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "synvow_prompt_test"
if PACKAGE_NAME not in sys.modules:
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE_NAME] = package

director_module = importlib.import_module(f"{PACKAGE_NAME}.h3_prompt_director_runninghub")


def valid_plan_json() -> str:
    return json.dumps(
        {
            "task_mode": "t2va",
            "content_mode": "auto",
            "duration_seconds": 8,
            "aspect_ratio": "16:9",
            "requirements": {
                "must_appear": ["an adult runner on a rain-wet overpass"],
                "must_keep": [],
                "allowed_change": [],
                "must_not_appear": [],
            },
            "image_references": [],
            "subjects": [],
            "shots": [
                {
                    "index": 1,
                    "start": 0.0,
                    "end": 8.0,
                    "camera": "steady medium tracking shot",
                    "subject_action": "An adult runner completes a final sprint and stops at the railing",
                    "performance": "Controlled exertion turns into quiet relief",
                    "environment_response": "white breath drifts through the cold post-rain air",
                    "visual_detail": "wet concrete reflects the first sunrise light",
                    "beat_cue": "hold the final breath before the end",
                    "state_change": "the action resolves into a calm sunrise look",
                    "transition_out": "hold the final composition",
                    "sound_instruction": "footsteps on wet concrete and a single deep breath",
                }
            ],
            "visual_system": {
                "creative_intent": "a restrained athletic dawn short film",
                "look": "realistic, cool-to-warm morning light",
                "camera_grammar": "steady, deliberate movement",
                "performance_rule": "natural exertion without posing",
            },
            "sound_system": {"overall_soundscape": "quiet city dawn ambience", "non_diegetic_music": ""},
            "constraints": [],
            "exact_dialogue": "",
            "text_whitelist": [],
        }
    )


class RunningHubH3DirectorTests(unittest.TestCase):
    def test_node_registers_chinese_h3_controls_and_domain_options(self):
        inputs = director_module.RunningHubH3MultiReferencePromptDirector.INPUT_TYPES()
        self.assertIn("RunningHub LLM 域名", inputs["required"])
        self.assertIn("音乐 MV / 情绪短片", inputs["required"]["内容类型"][0])
        self.assertEqual(inputs["optional"]["图片_1"], ("IMAGE",))
        self.assertEqual(inputs["optional"]["视频_3"], ("VIDEO",))
        self.assertTrue(inputs["required"]["随机种子"][1]["control_after_generate"])

    def test_cache_key_uses_images_and_seed_but_keeps_media_payload_opaque(self):
        base = {"创作需求": "雨后跑者", "随机种子": 401, "图片_1": np.zeros((1, 2, 2, 3), dtype=np.float32)}
        node = director_module.RunningHubH3MultiReferencePromptDirector
        first = node.IS_CHANGED(**base)
        self.assertEqual(first, node.IS_CHANGED(**base))
        self.assertNotEqual(first, node.IS_CHANGED(**{**base, "随机种子": 402}))
        self.assertNotEqual(first, node.IS_CHANGED(**{**base, "图片_1": np.ones((1, 2, 2, 3), dtype=np.float32)}))
        self.assertEqual(
            node.IS_CHANGED(**base, 视频_1=object()),
            node.IS_CHANGED(**base, 视频_1=object()),
        )

    def test_auto_domain_falls_back_from_ai_to_cn(self):
        class Response:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload
                self.text = "temporary failure" if status_code != 200 else ""

            def json(self):
                return self._payload

        calls = []

        def fake_post(url, **kwargs):
            calls.append(url)
            if url.endswith(".ai/v1/chat/completions"):
                return Response(503, {})
            return Response(200, {"choices": [{"message": {"content": "ok"}}]})

        with patch.object(director_module, "get_runninghub_api_key", return_value="test-key"), patch.object(
            director_module.requests, "post", side_effect=fake_post
        ):
            content, endpoint = director_module._chat_completion(
                "google/gemini-3.1-pro-preview",
                "system",
                "user",
                [],
                0,
                "自动（优先 .ai，失败回退 .cn）",
                None,
                temperature=0.2,
            )
        self.assertEqual(content, "ok")
        self.assertTrue(calls[0].endswith(".ai/v1/chat/completions"))
        self.assertTrue(calls[1].endswith(".cn/v1/chat/completions"))
        self.assertTrue(endpoint.endswith(".cn/v1/chat/completions"))

    def test_text_to_video_plan_renders_without_a_network_request(self):
        node = director_module.RunningHubH3MultiReferencePromptDirector()
        settings = {
            "模型": "google/gemini-3.1-pro-preview",
            "RunningHub LLM 域名": "RunningHub .cn",
            "创作需求": "8秒短片：雨后天桥上一位成年跑者完成冲刺。",
            "任务模式": "文生视频",
            "内容类型": "自动判断",
            "时长（秒）": 8,
            "画幅比例": "16:9",
            "运动强度": "标准",
            "镜头结构": "自动判断",
            "输出格式": "官方英文结构化+中文预览",
            "参考优先级": "图片身份优先",
            "自定义优先级规则": "",
            "未声明内容保持": True,
            "严格校验": True,
            "随机种子": 401,
        }
        with patch.object(director_module, "_chat_completion", return_value=(valid_plan_json(), "mock")):
            english, preview, _, manifest, report, debug = node.generate(**settings)
        self.assertIn("integrated_multimodal_description:", english)
        self.assertIn("Global visual direction:", english)
        self.assertIn("Timeline:", english)
        self.assertIn("任务：t2va", preview)
        self.assertEqual(json.loads(manifest)["videos"], [])
        self.assertTrue(json.loads(report)["is_valid"])
        self.assertEqual(json.loads(debug)["llm_endpoint"], "mock")


if __name__ == "__main__":
    unittest.main()
