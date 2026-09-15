import json
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops, ImageDraw
from psd_tools import PSDImage
import torch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "synvow_prompt_transparent_test"
if PACKAGE_NAME not in sys.modules:
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE_NAME] = package

composer = importlib.import_module(f"{PACKAGE_NAME}.psd_layer_composer")


class PsdLayerComposerTests(unittest.TestCase):
    def _write_layers(self, folder, size=(160, 120)):
        background = Image.new("RGBA", size, (30, 60, 90, 255))
        subject = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(subject).ellipse((40, 20, 120, 100), fill=(240, 90, 70, 255))
        text = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(text).rectangle((15, 90, 70, 105), fill=(255, 255, 255, 255))
        paths = []
        for index, image in enumerate((background, subject, text), start=1):
            path = Path(folder) / f"layer_{index}.png"
            image.save(path)
            image.close()
            paths.append(str(path))
        return paths

    def test_writes_reopenable_named_psd_layers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_layers(temp_dir)
            plan = {
                "items": [
                    {"name": "背景层"},
                    {"name": "主体层"},
                    {"name": "文字层"},
                ]
            }
            with mock.patch.object(composer.folder_paths, "get_output_directory", return_value=temp_dir):
                output = composer.SynVowPsdLayerComposer().compose(
                    "\n".join(paths),
                    filename_prefix="test_psd",
                    layer_plan_json=json.dumps(plan, ensure_ascii=False),
                )

            preview, psd_path, status = output["result"]
            self.assertEqual(tuple(preview.shape), (1, 120, 160, 3))
            self.assertTrue(Path(psd_path).is_file())
            reopened = PSDImage.open(psd_path)
            self.assertEqual(reopened.size, (160, 120))
            self.assertEqual([layer.name for layer in reopened], ["背景层", "主体层", "文字层"])
            self.assertTrue(reopened[1].has_mask())
            self.assertEqual(reopened.composite().size, (160, 120))
            preview_path = Path(temp_dir) / composer.PREVIEW_SUBFOLDER / output["ui"]["images"][0]["filename"]
            with Image.open(preview_path) as saved_preview:
                difference = ImageChops.difference(
                    saved_preview.convert("RGBA"),
                    reopened.composite(force=True).convert("RGBA"),
                )
                self.assertIsNone(difference.getbbox())
            self.assertIn("含透明像素图层=2/3", status)

    def test_manifest_reorders_generation_order_to_bottom_first(self):
        plan = {
            "layers": [
                {"key": "text_logo", "name": "文字层"},
                {"key": "subject_product", "name": "主体层"},
                {"key": "background", "name": "背景层"},
            ],
            "layer_order_bottom_to_top": ["background", "subject_product", "text_logo"],
        }
        records = composer._parse_plan(json.dumps(plan, ensure_ascii=False), 3)
        self.assertEqual([record["name"] for record in records], ["背景层", "主体层", "文字层"])
        self.assertEqual([record["source_index"] for record in records], [2, 1, 0])

    def test_mismatched_canvas_sizes_are_normalized_and_composed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.png"
            second = Path(temp_dir) / "second.png"
            Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(first)
            Image.new("RGBA", (120, 100), (0, 0, 0, 0)).save(second)
            with mock.patch.object(composer.folder_paths, "get_output_directory", return_value=temp_dir):
                output = composer.SynVowPsdLayerComposer().compose(f"{first}\n{second}")
            _, psd_path, _ = output["result"]
            reopened = PSDImage.open(psd_path)
            self.assertEqual(reopened.size, (100, 100))
            self.assertEqual(len(reopened), 2)

    def test_absolute_save_path_is_used(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "comfy_output"
            custom_dir = Path(temp_dir) / "custom_psd"
            paths = self._write_layers(temp_dir)
            with mock.patch.object(composer.folder_paths, "get_output_directory", return_value=str(output_dir)):
                output = composer.SynVowPsdLayerComposer().compose(
                    "\n".join(paths),
                    filename_prefix="custom",
                    save_path=str(custom_dir),
                )
            _, psd_path, status = output["result"]
            self.assertEqual(Path(psd_path).parent, custom_dir)
            self.assertTrue(Path(psd_path).is_file())
            self.assertIn(str(custom_dir), status)

    def test_reference_image_sets_canvas_and_adds_hidden_reference_layer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_layers(temp_dir, size=(160, 120))
            reference = torch.zeros((1, 180, 100, 3), dtype=torch.float32)
            with mock.patch.object(composer.folder_paths, "get_output_directory", return_value=temp_dir):
                output = composer.SynVowPsdLayerComposer().compose(
                    "\n".join(paths),
                    reference_image=reference,
                )
            preview, psd_path, status = output["result"]
            reopened = PSDImage.open(psd_path)
            self.assertEqual(reopened.size, (160, 120))
            self.assertEqual(reopened[0].name, "原图参考（隐藏）")
            self.assertFalse(reopened[0].visible)
            self.assertEqual(tuple(preview.shape), (1, 120, 160, 3))
            self.assertIn("PNG图层原样写入PSD", status)


if __name__ == "__main__":
    unittest.main()
