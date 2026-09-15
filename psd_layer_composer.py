# -*- coding: utf-8 -*-
"""Compose saved RGBA PNG layers into an editable PSD file."""

import json
import os
import re
from typing import Dict, List

import folder_paths
import numpy as np
import torch
from PIL import Image

try:
    from psd_tools import PSDImage
except ImportError:
    PSDImage = None


CATEGORY = "SynVow-prompt/透明素材"
DEFAULT_SAVE_PATH = "SynVowPSD"
PREVIEW_SUBFOLDER = "SynVowPSDPreview"
DEFAULT_LAYER_NAMES = {
    2: ["背景层", "主体/人物/产品层"],
    3: ["背景层", "主体/人物/产品层", "文字/Logo层"],
    4: ["背景层", "主体/人物/产品层", "文字/Logo层", "装饰元素层"],
    5: ["背景层", "主体/人物/产品层", "文字/Logo层", "装饰元素层", "光影氛围层"],
    6: ["背景层", "主体/人物/产品层", "文字/Logo层", "装饰元素层", "光影氛围层", "其他可复用元素层"],
}


def _unpack(value):
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def _collect_paths(value) -> List[str]:
    value = _unpack(value)
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    paths = []
    for item in values:
        if item is None:
            continue
        text = str(item).strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    paths.extend(str(path).strip() for path in parsed if path)
                    continue
            except json.JSONDecodeError:
                pass
        for line in text.splitlines():
            path = line.strip().strip('"')
            if path and path.lower() != "null":
                paths.append(path)
    return paths


def _safe_prefix(value) -> str:
    text = str(_unpack(value) or "layer_split").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip(" ._")
    return text or "layer_split"


def _resolve_save_folder(output_dir: str, save_path) -> str:
    raw = str(_unpack(save_path) or DEFAULT_SAVE_PATH).strip().strip('"')
    if re.match(r"^[A-Za-z]:[\\/]", raw) or os.path.isabs(raw):
        folder = os.path.abspath(raw)
    else:
        parts = []
        for part in raw.replace("\\", "/").split("/"):
            part = part.strip()
            if not part or part in {".", ".."}:
                continue
            parts.append(re.sub(r'[<>:"|?*\x00-\x1f]', "_", part))
        relative = os.path.join(*parts) if parts else DEFAULT_SAVE_PATH
        folder = os.path.join(output_dir, relative)
    os.makedirs(folder, exist_ok=True)
    return folder


def _parse_plan(value, count: int) -> List[Dict[str, str]]:
    raw = str(_unpack(value) or "").strip()
    data = {}
    if raw:
        try:
            parsed = json.loads(raw)
            data = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            data = {}

    source = data.get("layers") if isinstance(data.get("layers"), list) else data.get("items")
    source = source if isinstance(source, list) else []
    records = []
    for index in range(count):
        item = source[index] if index < len(source) and isinstance(source[index], dict) else {}
        records.append({
            "source_index": index,
            "key": str(item.get("key") or ""),
            "name": str(item.get("name") or item.get("layer_name") or "").strip(),
        })

    desired_order = data.get("layer_order_bottom_to_top")
    if isinstance(desired_order, list) and any(record["key"] for record in records):
        positions = {str(key): index for index, key in enumerate(desired_order)}
        records.sort(key=lambda record: positions.get(record["key"], len(positions) + record["source_index"]))

    fallback = DEFAULT_LAYER_NAMES.get(count, [f"图层 {index:02d}" for index in range(1, count + 1)])
    for index, record in enumerate(records):
        if not record["name"]:
            record["name"] = fallback[index] if index < len(fallback) else f"图层 {index + 1:02d}"
    return records


def _next_output_paths(output_dir: str, save_folder: str, prefix: str):
    preview_folder = os.path.join(output_dir, PREVIEW_SUBFOLDER)
    os.makedirs(preview_folder, exist_ok=True)
    counter = 1
    while True:
        stem = f"{prefix}_{counter:05d}"
        psd_path = os.path.join(save_folder, f"{stem}.psd")
        preview_path = os.path.join(preview_folder, f"{stem}_preview.png")
        if not os.path.exists(psd_path) and not os.path.exists(preview_path):
            return psd_path, preview_path, f"{stem}_preview.png"
        counter += 1


def _pil_to_tensor(image: Image.Image) -> torch.Tensor:
    array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _load_rgba(path: str) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _tensor_to_rgba(value) -> Image.Image:
    tensor = _unpack(value)
    if tensor is None:
        return None
    array = tensor[0].detach().cpu().numpy()
    array = (array * 255).clip(0, 255).astype(np.uint8)
    if array.shape[-1] >= 4:
        return Image.fromarray(array[..., :4], "RGBA")
    return Image.fromarray(array[..., :3], "RGB").convert("RGBA")


def _fit_to_canvas(image: Image.Image, target_size) -> Image.Image:
    target_width, target_height = target_size
    if image.size == target_size:
        return image
    source_width, source_height = image.size
    source_ratio = source_width / source_height
    target_ratio = target_width / target_height
    if source_ratio > target_ratio:
        crop_width = max(1, round(source_height * target_ratio))
        left = max(0, (source_width - crop_width) // 2)
        box = (left, 0, left + crop_width, source_height)
    else:
        crop_height = max(1, round(source_width / target_ratio))
        top = max(0, (source_height - crop_height) // 2)
        box = (0, top, source_width, top + crop_height)
    cropped = image.crop(box)
    fitted = cropped.resize(target_size, Image.Resampling.LANCZOS)
    cropped.close()
    return fitted


class SynVowPsdLayerComposer:
    FUNCTION = "compose"
    CATEGORY = CATEGORY
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("composite_preview", "psd_file_path", "status")
    OUTPUT_NODE = True
    INPUT_IS_LIST = True
    DESCRIPTION = "将透明PNG保存节点输出的RGBA文件按顺序写入可编辑PSD图层。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "rgba_file_paths": ("STRING", {"forceInput": True}),
                "filename_prefix": ("STRING", {"default": "layer_split"}),
                "save_path": ("STRING", {"default": DEFAULT_SAVE_PATH}),
            },
            "optional": {
                "layer_plan_json": ("STRING", {"forceInput": True}),
                "reference_image": ("IMAGE",),
            },
        }

    def compose(
        self,
        rgba_file_paths,
        filename_prefix="layer_split",
        save_path=DEFAULT_SAVE_PATH,
        layer_plan_json="",
        reference_image=None,
    ):
        if PSDImage is None:
            raise RuntimeError("缺少 psd-tools>=1.19，请重新安装插件依赖并重启ComfyUI。")

        paths = _collect_paths(rgba_file_paths)
        if not paths:
            raise ValueError("没有收到可用的 rgba_file_paths。")

        missing = [path for path in paths if not os.path.isfile(path)]
        if missing:
            raise FileNotFoundError(f"图层文件不存在：{missing[0]}")

        source_images = [_load_rgba(path) for path in paths]
        reference = _tensor_to_rgba(reference_image)
        try:
            canvas_size = source_images[0].size
            normalized_count = 0
            for index, image in enumerate(source_images):
                if image.size != canvas_size:
                    fitted = _fit_to_canvas(image, canvas_size)
                    image.close()
                    source_images[index] = fitted
                    normalized_count += 1
            if reference is not None and reference.size != canvas_size:
                fitted_reference = _fit_to_canvas(reference, canvas_size)
                reference.close()
                reference = fitted_reference

            records = _parse_plan(layer_plan_json, len(paths))
            ordered_images = [source_images[record["source_index"]] for record in records]

            psd = PSDImage.new(mode="RGB", size=canvas_size, depth=8)
            expected_names = []
            if reference is not None:
                reference_layer = psd.create_pixel_layer(reference, name="Layer", top=0, left=0)
                reference_layer.name = "原图参考（隐藏）"
                reference_layer.visible = False
                expected_names.append(reference_layer.name)
            for record, image in zip(records, ordered_images):
                layer = psd.create_pixel_layer(image, name="Layer", top=0, left=0)
                layer.name = record["name"]
                expected_names.append(layer.name)

            output_dir = folder_paths.get_output_directory()
            save_folder = _resolve_save_folder(output_dir, save_path)
            psd_path, preview_path, preview_filename = _next_output_paths(
                output_dir,
                save_folder,
                _safe_prefix(filename_prefix),
            )
            psd.save(psd_path)

            composite = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            for image in ordered_images:
                composite = Image.alpha_composite(composite, image)
            composite.save(preview_path, format="PNG")

            reopened = PSDImage.open(psd_path)
            actual_names = [layer.name for layer in reopened]
            if reopened.size != canvas_size or actual_names != expected_names:
                raise RuntimeError("PSD回读校验失败：画布尺寸或图层顺序不一致。")

            alpha_layers = sum(image.getchannel("A").getextrema()[0] < 255 for image in ordered_images)
            status = (
                f"PSD已保存：{len(records)}层，画布={canvas_size[0]}x{canvas_size[1]}，"
                f"含透明像素图层={alpha_layers}/{len(records)}；顺序=背景到前景；目录={save_folder}。"
            )
            if reference is not None:
                reference_rgb = np.asarray(reference.convert("RGB"), dtype=np.float32)
                composite_rgb = np.asarray(composite.convert("RGB"), dtype=np.float32)
                difference = float(np.mean(np.abs(reference_rgb - composite_rgb)) / 255.0 * 100.0)
                status += (
                    f" 已加入隐藏原图参考层；PNG图层原样写入PSD，节点内二次归一化 {normalized_count}/{len(records)} 层；"
                    f"合成与原图平均像素差异={difference:.1f}%。"
                )
            return {
                "ui": {
                    "images": [{
                        "filename": preview_filename,
                        "subfolder": PREVIEW_SUBFOLDER,
                        "type": "output",
                    }]
                },
                "result": (_pil_to_tensor(composite), psd_path, status),
            }
        finally:
            for image in source_images:
                image.close()
            if reference is not None:
                reference.close()


NODE_CLASS_MAPPINGS = {
    "SynVowPsdLayerComposer": SynVowPsdLayerComposer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SynVowPsdLayerComposer": "SynVow PSD图层合成",
}
