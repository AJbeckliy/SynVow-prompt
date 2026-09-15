import json
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import torch
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "synvow_prompt_transparent_test"
if PACKAGE_NAME not in sys.modules:
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE_NAME] = package

transparent_save = importlib.import_module(f"{PACKAGE_NAME}.transparent_png_save_preview")


class TransparentPngSavePreviewTests(unittest.TestCase):
    def _save_path(self, root):
        return (root, "transparent", 1, "SynVowTransparent", "transparent")

    def test_empty_url_returns_saved_black_placeholder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            node = transparent_save.SynVowTransparentPngSavePreview()
            node.output_dir = temp_dir
            with mock.patch.object(
                transparent_save.folder_paths,
                "get_save_image_path",
                return_value=self._save_path(temp_dir),
            ):
                output = node.save(["[ERROR] upstream generation failed"])

            tensors, paths, status = output["result"]
            self.assertEqual(len(tensors), 1)
            self.assertEqual(tuple(tensors[0].shape), (1, 1024, 1024, 3))
            self.assertTrue(torch.count_nonzero(tensors[0]).item() == 0)
            saved_path = Path(paths)
            self.assertTrue(saved_path.is_file())
            with Image.open(saved_path) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 255))
            self.assertIn("上游失败黑图占位 1/1", status)
            self.assertIn("工作流已继续", status)

    def test_partial_download_failure_preserves_batch_with_black_placeholder(self):
        valid = Image.new("RGBA", (8, 6), (255, 0, 0, 0))
        with tempfile.TemporaryDirectory() as temp_dir:
            node = transparent_save.SynVowTransparentPngSavePreview()
            node.output_dir = temp_dir
            with (
                mock.patch.object(
                    transparent_save,
                    "_download_rgba_images",
                    return_value=[valid, None],
                ),
                mock.patch.object(
                    transparent_save.folder_paths,
                    "get_save_image_path",
                    return_value=self._save_path(temp_dir),
                ),
            ):
                output = node.save(["https://example.test/one.png\nhttps://example.test/two.png"])

            tensors, paths, status = output["result"]
            self.assertEqual(len(tensors), 2)
            self.assertEqual(tuple(tensors[1].shape), (1, 6, 8, 3))
            self.assertTrue(torch.count_nonzero(tensors[1]).item() == 0)
            self.assertEqual(len(paths.splitlines()), 2)
            self.assertIn("URL原图保存 1/2", status)
            self.assertIn("上游失败黑图占位 1/2", status)

    def test_alpha_node_placeholder_tokens_create_matching_black_slots(self):
        value = "\n".join([
            f"{transparent_save.BLACK_PLACEHOLDER_TOKEN}:1",
            f"{transparent_save.BLACK_PLACEHOLDER_TOKEN}:2",
            f"{transparent_save.BLACK_PLACEHOLDER_TOKEN}:3",
            f"{transparent_save.BLACK_PLACEHOLDER_TOKEN}:4",
        ])
        reference = torch.zeros((1, 9, 5, 3), dtype=torch.float32)
        with tempfile.TemporaryDirectory() as temp_dir:
            node = transparent_save.SynVowTransparentPngSavePreview()
            node.output_dir = temp_dir
            with mock.patch.object(
                transparent_save.folder_paths,
                "get_save_image_path",
                return_value=self._save_path(temp_dir),
            ):
                output = node.save([value], reference_image=reference)
            tensors, paths, status = output["result"]
            self.assertEqual(len(tensors), 4)
            self.assertTrue(all(tuple(tensor.shape) == (1, 9, 5, 3) for tensor in tensors))
            self.assertTrue(all(torch.count_nonzero(tensor).item() == 0 for tensor in tensors))
            self.assertEqual(len(paths.splitlines()), 4)
            self.assertIn("上游失败黑图占位 4/4", status)

    def test_mixed_url_and_placeholder_tokens_keep_batch_order(self):
        valid = Image.new("RGBA", (8, 6), (255, 0, 0, 255))
        value = "\n".join([
            f"{transparent_save.BLACK_PLACEHOLDER_TOKEN}:1",
            "https://example.test/two.png",
            f"{transparent_save.BLACK_PLACEHOLDER_TOKEN}:3",
        ])
        with tempfile.TemporaryDirectory() as temp_dir:
            node = transparent_save.SynVowTransparentPngSavePreview()
            node.output_dir = temp_dir
            with (
                mock.patch.object(transparent_save, "_download_rgba_images", return_value=[valid]),
                mock.patch.object(
                    transparent_save.folder_paths,
                    "get_save_image_path",
                    return_value=self._save_path(temp_dir),
                ),
            ):
                output = node.save([value])
            tensors, _, status = output["result"]
            self.assertEqual(len(tensors), 3)
            self.assertTrue(torch.count_nonzero(tensors[0]).item() == 0)
            self.assertTrue(torch.count_nonzero(tensors[1]).item() > 0)
            self.assertTrue(torch.count_nonzero(tensors[2]).item() == 0)
            self.assertIn("上游失败黑图占位 2/3", status)

    def test_reference_image_normalizes_saved_canvas(self):
        source = Image.new("RGBA", (8, 8), (255, 0, 0, 128))
        reference = torch.zeros((1, 9, 5, 3), dtype=torch.float32)
        with tempfile.TemporaryDirectory() as temp_dir:
            node = transparent_save.SynVowTransparentPngSavePreview()
            node.output_dir = temp_dir
            with (
                mock.patch.object(transparent_save, "_download_rgba_images", return_value=[source]),
                mock.patch.object(
                    transparent_save.folder_paths,
                    "get_save_image_path",
                    return_value=self._save_path(temp_dir),
                ),
            ):
                output = node.save(
                    ["https://example.test/layer.png"],
                    reference_image=reference,
                )
            tensors, paths, status = output["result"]
            self.assertEqual(tuple(tensors[0].shape), (1, 9, 5, 3))
            with Image.open(paths) as image:
                self.assertEqual(image.size, (5, 9))
            self.assertIn("目标尺寸 5x9", status)

    def test_reference_split_preserves_downloaded_rgba_without_resizing(self):
        pixels = np.zeros((6, 8, 4), dtype=np.uint8)
        pixels[:, :, :3] = (12, 34, 56)
        pixels[:, :, 3] = np.arange(8, dtype=np.uint8)[None, :] * 30
        source = Image.fromarray(pixels, "RGBA")
        reference = torch.zeros((1, 9, 5, 3), dtype=torch.float32)
        prompt = {
            "12": {
                "class_type": "SynVowTransparentAssetPromptGenerator",
                "inputs": {"scene_preset": "参考图分层拆图", "layer_count": "4"},
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            node = transparent_save.SynVowTransparentPngSavePreview()
            node.output_dir = temp_dir
            with (
                mock.patch.object(transparent_save, "_download_rgba_images", return_value=[source]),
                mock.patch.object(
                    transparent_save.folder_paths,
                    "get_save_image_path",
                    return_value=self._save_path(temp_dir),
                ),
            ):
                output = node.save(
                    ["https://example.test/layer.png"],
                    reference_image=reference,
                    prompt=prompt,
                )
            _, path, status = output["result"]
            with Image.open(path).convert("RGBA") as saved:
                self.assertEqual(saved.size, (8, 6))
                self.assertTrue(np.array_equal(np.asarray(saved), pixels))
            self.assertIn("已原样保存 Image 2.5 返回的 RGBA PNG", status)

    def test_split_geometry_plan_places_layers_and_forces_opaque_background(self):
        background = Image.new("RGBA", (100, 200), (240, 240, 240, 0))
        for y in range(10, 190):
            for x in range(100):
                background.putpixel((x, y), (240, 240, 240, 255))
        foreground = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
        for y in range(50, 150):
            for x in range(10, 90):
                foreground.putpixel((x, y), (255, 0, 0, 255))
        plan = json.dumps({
            "items": [
                {"name": "背景层", "geometry": {"layer_bbox_normalized": [0, 0, 1, 1]}},
                {"name": "主体/人物/产品层", "geometry": {"layer_bbox_normalized": [0.2, 0.4, 0.8, 0.7]}},
            ]
        }, ensure_ascii=False)
        normalized, size, count = transparent_save._normalize_split_rgba_layers(
            [background, foreground],
            transparent_save._layer_records_from_plan(plan, 2),
            0,
            (50, 100),
        )
        self.assertEqual(size, (96, 200))
        self.assertEqual(count, 2)
        self.assertEqual(normalized[0].getchannel("A").getextrema(), (255, 255))
        self.assertEqual(transparent_save._alpha_content_bbox(normalized[1]), (19, 80, 77, 140))

    def test_non_object_layer_plan_falls_back_to_empty_records(self):
        self.assertEqual(
            transparent_save._layer_records_from_plan('[{"name": "背景层"}]', 2),
            [{}, {}],
        )

    def test_photo_like_light_gradient_is_not_repaired_as_checkerboard(self):
        width = height = 128
        gradient = np.tile(np.linspace(185, 255, width, dtype=np.uint8), (height, 1))
        rgb = np.stack([gradient, gradient, gradient], axis=-1)
        image = Image.fromarray(rgb, "RGB").convert("RGBA")
        repaired, info = transparent_save._repair_fake_checkerboard_alpha(image)
        self.assertEqual(info, "")
        self.assertEqual(repaired.getchannel("A").getextrema(), (255, 255))

    def test_regular_checkerboard_is_repaired(self):
        tile = 16
        size = 128
        array = np.zeros((size, size, 4), dtype=np.uint8)
        for y in range(size):
            for x in range(size):
                value = 250 if ((x // tile) + (y // tile)) % 2 == 0 else 205
                array[y, x] = (value, value, value, 255)
        image = Image.fromarray(array, "RGBA")
        repaired, info = transparent_save._repair_fake_checkerboard_alpha(image)
        self.assertTrue(info.startswith("checkerboard_to_alpha:"))
        self.assertEqual(repaired.getchannel("A").getextrema()[0], 0)

    def test_known_foreground_can_use_aggressive_checkerboard_repair(self):
        width = height = 128
        gradient = np.tile(np.linspace(185, 255, width, dtype=np.uint8), (height, 1))
        rgb = np.stack([gradient, gradient, gradient], axis=-1)
        image = Image.fromarray(rgb, "RGB").convert("RGBA")
        repaired, info = transparent_save._repair_fake_checkerboard_alpha(
            image,
            require_regular_pattern=False,
        )
        self.assertTrue(info.startswith("checkerboard_to_alpha:"))
        self.assertEqual(repaired.getchannel("A").getextrema()[0], 0)

    def test_foreground_contain_fit_does_not_crop(self):
        image = Image.new("RGBA", (8, 4), (255, 0, 0, 255))
        fitted = transparent_save._fit_rgba_to_size(image, (8, 8), mode="contain")
        self.assertEqual(fitted.getchannel("A").getbbox(), (0, 2, 8, 6))

    def test_split_layer_order_is_inferred_from_workflow_prompt(self):
        prompt = {
            "12": {
                "class_type": "SynVowTransparentAssetPromptGenerator",
                "inputs": {
                    "scene_preset": "参考图分层拆图",
                    "layer_count": "4",
                },
            }
        }
        names = transparent_save._infer_split_layer_names_from_prompt(prompt, 4)
        self.assertEqual(names, ["背景层", "主体/人物/产品层", "文字/Logo层", "装饰元素层"])
        self.assertEqual(transparent_save._background_layer_index(names), 0)

if __name__ == "__main__":
    unittest.main()
