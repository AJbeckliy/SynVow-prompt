# -*- coding: utf-8 -*-
"""Save transparent PNG images directly from original image URLs."""

import json
import io
import os
import random
import re
from collections import deque
from typing import List, Optional

import numpy as np
import requests
import torch
import urllib3
from PIL import Image
from PIL.PngImagePlugin import PngInfo

import folder_paths
from comfy.cli_args import args


CATEGORY = "SynVow-prompt/透明素材"
DEFAULT_PLACEHOLDER_SIZE = (1024, 1024)
BLACK_PLACEHOLDER_TOKEN = "__SYNVOW_BLACK_PLACEHOLDER__"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _unpack(value):
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def _safe_relative_path(value, default="") -> str:
    text = str(_unpack(value) or default).strip().replace("\\", "/")
    text = re.sub(r"^[A-Za-z]:", "", text).strip("/")
    parts = []
    for part in text.split("/"):
        part = part.strip()
        if not part or part in {".", ".."}:
            continue
        parts.append(re.sub(r'[<>:"|?*\x00-\x1f]', "_", part))
    return "/".join(parts)


def _safe_filename_prefix(value, default="transparent") -> str:
    text = _safe_relative_path(value, default=default)
    text = text.replace("/", "_").strip("_")
    return text or default


def _raw_path(value, default="") -> str:
    return str(_unpack(value) or default).strip().strip('"')


def _is_absolute_save_path(value: str) -> bool:
    text = str(value or "").strip()
    return bool(re.match(r"^[A-Za-z]:[\\/]", text)) or os.path.isabs(text)


def _next_counter(folder: str, filename_prefix: str) -> int:
    counter = 1
    while True:
        candidate = os.path.join(folder, f"{filename_prefix}_{counter:05}_alpha.png")
        if not os.path.exists(candidate):
            return counter
        counter += 1


def _next_available_png_path(folder: str, filename_prefix: str, start_counter: int) -> tuple:
    counter = max(1, int(start_counter or 1))
    while True:
        filename = f"{filename_prefix}_{counter:05}_alpha.png"
        path = os.path.join(folder, filename)
        if not os.path.exists(path):
            return path, filename, counter
        counter += 1


def _collect_source_slots(value) -> List[Optional[str]]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    slots = []
    for item in items:
        if item is None:
            slots.append(None)
            continue
        lines = str(item).splitlines() or [str(item)]
        for line in lines:
            if BLACK_PLACEHOLDER_TOKEN in line:
                slots.append(None)
                continue
            for url in re.findall(r"https?://[^\s\"'<>]+", line):
                cleaned = url.rstrip("),，。；;")
                if cleaned:
                    slots.append(cleaned)
    return slots


def _collect_urls(value) -> List[str]:
    return [url for url in _collect_source_slots(value) if url]


def _download_rgba_from_url(url: str) -> Optional[Image.Image]:
    short = f"...{url[-24:]}" if len(url) > 24 else url
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=120, verify=False)
            response.raise_for_status()
            rgba = Image.open(io.BytesIO(response.content)).convert("RGBA")
            print(f"[SynVowTransparentSave] URL RGBA 下载成功 ({attempt + 1}/3): {short} {rgba.width}x{rgba.height}")
            return rgba
        except Exception as exc:
            print(f"[SynVowTransparentSave] URL RGBA 下载失败 ({attempt + 1}/3): {short} {exc}")
    return None


def _download_rgba_images(urls: List[str]) -> List[Optional[Image.Image]]:
    result = []
    for url in urls:
        result.append(_download_rgba_from_url(url))
    return result


def _download_source_slots(slots: List[Optional[str]]) -> List[Optional[Image.Image]]:
    downloaded = iter(_download_rgba_images([url for url in slots if url]))
    return [next(downloaded) if url else None for url in slots]


def _rgba_pil_to_tensor(image: Image.Image) -> torch.Tensor:
    array = np.asarray(image.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _reference_canvas_size(value):
    tensor = _unpack(value)
    shape = getattr(tensor, "shape", None)
    if shape is None or len(shape) < 3:
        return None
    height = int(shape[-3])
    width = int(shape[-2])
    return (width, height) if width > 0 and height > 0 else None


def _fit_rgba_to_size(image: Image.Image, target_size, mode="contain") -> Image.Image:
    if image.size == target_size:
        return image
    target_width, target_height = target_size
    source_width, source_height = image.size
    source_ratio = source_width / source_height
    target_ratio = target_width / target_height
    if mode == "contain":
        scale = min(target_width / source_width, target_height / source_height)
        fitted_size = (
            max(1, round(source_width * scale)),
            max(1, round(source_height * scale)),
        )
        resized = image.resize(fitted_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", target_size, (0, 0, 0, 0))
        canvas.alpha_composite(
            resized,
            ((target_width - fitted_size[0]) // 2, (target_height - fitted_size[1]) // 2),
        )
        resized.close()
        return canvas
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


def _layer_names_from_plan(value, count: int) -> List[str]:
    raw = str(_unpack(value) or "").strip()
    if not raw:
        return [""] * count
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [""] * count
    if not isinstance(data, dict):
        return [""] * count
    source = data.get("layers") if isinstance(data.get("layers"), list) else data.get("items")
    source = source if isinstance(source, list) else []
    names = []
    for index in range(count):
        item = source[index] if index < len(source) and isinstance(source[index], dict) else {}
        names.append(str(item.get("name") or item.get("layer_name") or ""))
    return names


def _layer_records_from_plan(value, count: int) -> List[dict]:
    raw = str(_unpack(value) or "").strip()
    if not raw:
        return [{} for _ in range(count)]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [{} for _ in range(count)]
    if not isinstance(data, dict):
        return [{} for _ in range(count)]
    source = data.get("layers") if isinstance(data.get("layers"), list) else data.get("items", [])
    source = source if isinstance(source, list) else []
    return [source[index] if index < len(source) and isinstance(source[index], dict) else {} for index in range(count)]


def _scaled_reference_canvas(reference_size, generated_size):
    reference_width, reference_height = reference_size
    generated_width, generated_height = generated_size
    target_long = max(generated_width, generated_height)
    if reference_width >= reference_height:
        width = target_long
        height = max(16, round((target_long * reference_height / reference_width) / 16) * 16)
    else:
        height = target_long
        width = max(16, round((target_long * reference_width / reference_height) / 16) * 16)
    return width, height


def _alpha_content_bbox(image: Image.Image, threshold=128):
    alpha = np.asarray(image.convert("RGBA").getchannel("A"), dtype=np.uint8)
    ys, xs = np.where(alpha >= threshold)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def _planned_layer_bbox(record: dict):
    geometry = record.get("geometry") if isinstance(record.get("geometry"), dict) else record
    value = geometry.get("layer_bbox_normalized") or geometry.get("bbox_normalized")
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (max(0.0, min(1.0, float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def _normalize_split_rgba_layers(images, records, background_index, reference_size):
    valid = next((image for image in images if image is not None), None)
    if valid is None:
        return images, reference_size, 0
    target_size = _scaled_reference_canvas(reference_size, valid.size)
    normalized = []
    adjusted = 0
    for index, image in enumerate(images):
        if image is None:
            normalized.append(None)
            continue
        rgba = image.convert("RGBA")
        if index == background_index:
            content_bbox = _alpha_content_bbox(rgba)
            source = rgba.crop(content_bbox) if content_bbox else rgba
            result = source.resize(target_size, Image.Resampling.LANCZOS)
            result.putalpha(Image.new("L", target_size, 255))
            if source is not rgba:
                source.close()
            adjusted += 1
        else:
            planned_bbox = _planned_layer_bbox(records[index] if index < len(records) else {})
            content_bbox = _alpha_content_bbox(rgba)
            if planned_bbox and content_bbox:
                left = round(planned_bbox[0] * target_size[0])
                top = round(planned_bbox[1] * target_size[1])
                right = round(planned_bbox[2] * target_size[0])
                bottom = round(planned_bbox[3] * target_size[1])
                crop = rgba.crop(content_bbox)
                fitted = crop.resize((max(1, right - left), max(1, bottom - top)), Image.Resampling.LANCZOS)
                result = Image.new("RGBA", target_size, (0, 0, 0, 0))
                result.alpha_composite(fitted, (left, top))
                crop.close()
                fitted.close()
                adjusted += 1
            else:
                result = rgba.resize(target_size, Image.Resampling.LANCZOS)
        if result is not rgba:
            rgba.close()
        normalized.append(result)
    return normalized, target_size, adjusted


def _background_layer_index(layer_names: List[str]) -> Optional[int]:
    return next((index for index, name in enumerate(layer_names) if "背景" in name), None)


def _infer_split_layer_names_from_prompt(prompt, count: int) -> List[str]:
    prompt = _unpack(prompt)
    if not isinstance(prompt, dict):
        return [""] * count
    schemes = {
        2: ["背景层", "主体/人物/产品层"],
        3: ["背景层", "主体/人物/产品层", "文字/Logo层"],
        4: ["背景层", "主体/人物/产品层", "文字/Logo层", "装饰元素层"],
        5: ["背景层", "主体/人物/产品层", "文字/Logo层", "装饰元素层", "光影氛围层"],
        6: ["背景层", "主体/人物/产品层", "文字/Logo层", "装饰元素层", "光影氛围层", "其他可复用元素层"],
    }
    for node in prompt.values():
        if not isinstance(node, dict) or node.get("class_type") != "SynVowTransparentAssetPromptGenerator":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        if "参考图分层拆图" not in str(_unpack(inputs.get("scene_preset")) or ""):
            continue
        layer_count = int(_unpack(inputs.get("layer_count")) or count or 4)
        names = schemes.get(max(2, min(layer_count, 6)), schemes[4])
        return (names + [""] * count)[:count]
    return [""] * count


def _has_real_alpha(image: Image.Image) -> bool:
    alpha = image.convert("RGBA").getchannel("A")
    return bool(min(alpha.getdata()) < 255)


def _border_connected_mask(candidate: np.ndarray) -> np.ndarray:
    height, width = candidate.shape
    connected = np.zeros((height, width), dtype=bool)
    queue = deque()

    def add(y, x):
        if candidate[y, x] and not connected[y, x]:
            connected[y, x] = True
            queue.append((y, x))

    for x in range(width):
        add(0, x)
        add(height - 1, x)
    for y in range(height):
        add(y, 0)
        add(y, width - 1)

    while queue:
        y, x = queue.popleft()
        if y > 0:
            add(y - 1, x)
        if y + 1 < height:
            add(y + 1, x)
        if x > 0:
            add(y, x - 1)
        if x + 1 < width:
            add(y, x + 1)
    return connected


def _regular_border_checkerboard(gray: np.ndarray) -> bool:
    height, width = gray.shape
    if height < 16 or width < 16:
        return False
    border_lines = (gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1])
    regular_lines = 0
    for line in border_lines:
        line = np.asarray(line, dtype=np.float32)
        low = float(np.percentile(line, 20))
        high = float(np.percentile(line, 80))
        if high - low < 18:
            continue
        threshold = (low + high) / 2.0
        binary = line >= threshold
        transitions = np.flatnonzero(binary[1:] != binary[:-1]) + 1
        if transitions.size < 3:
            continue
        runs = np.diff(np.concatenate(([0], transitions, [line.size])))
        middle_runs = runs[1:-1] if runs.size > 2 else runs
        if middle_runs.size < 2 or float(np.mean(middle_runs)) < 2:
            continue
        variation = float(np.std(middle_runs) / max(np.mean(middle_runs), 1.0))
        if variation <= 0.45:
            regular_lines += 1
    return regular_lines >= 2


def _repair_fake_checkerboard_alpha(image: Image.Image, require_regular_pattern=True) -> tuple:
    rgba = image.convert("RGBA")
    if _has_real_alpha(rgba):
        return rgba, ""

    array = np.asarray(rgba).copy()
    rgb = array[:, :, :3].astype(np.int16)
    channel_max = rgb.max(axis=2)
    channel_min = rgb.min(axis=2)
    gray = rgb.mean(axis=2)

    light_neutral = (channel_max - channel_min <= 24) & (gray >= 175)
    connected = _border_connected_mask(light_neutral)
    bg_ratio = float(connected.mean())
    if bg_ratio < 0.08:
        return rgba, ""

    bg_gray = gray[connected]
    if bg_gray.size < 256:
        return rgba, ""

    spread = float(np.percentile(bg_gray, 95) - np.percentile(bg_gray, 5))
    light_ratio = float(np.mean(bg_gray >= 238))
    mid_ratio = float(np.mean((bg_gray >= 185) & (bg_gray <= 232)))
    if spread < 12:
        return rgba, ""
    if require_regular_pattern:
        if light_ratio < 0.08 or mid_ratio < 0.08:
            return rgba, ""
        if not _regular_border_checkerboard(gray):
            return rgba, ""
    elif mid_ratio < 0.20:
        return rgba, ""

    array[connected, :3] = 0
    array[connected, 3] = 0
    repaired = Image.fromarray(array, "RGBA")
    return repaired, f"checkerboard_to_alpha:{bg_ratio:.0%}"


class SynVowTransparentPngSavePreview:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_urls": ("STRING", {"forceInput": True}),
                "save_path": ("STRING", {"default": "SynVowTransparent"}),
                "filename_prefix": ("STRING", {"default": "transparent"}),
            },
            "optional": {
                "reference_image": ("IMAGE",),
                "layer_plan_json": ("STRING", {"forceInput": True}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("saved_images", "rgba_file_paths", "status")
    FUNCTION = "save"
    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True, False, False)
    OUTPUT_NODE = True
    CATEGORY = CATEGORY
    DESCRIPTION = "从 image_urls 下载原始 RGBA PNG；空 URL 或下载失败时输出黑图占位，避免中断工作流。"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return random.random()

    def save(
        self,
        image_urls,
        save_path="SynVowTransparent",
        filename_prefix="transparent",
        reference_image=None,
        layer_plan_json="",
        prompt=None,
        extra_pnginfo=None,
    ):
        raw_save_path = _raw_path(save_path, default="SynVowTransparent")
        is_absolute_save = _is_absolute_save_path(raw_save_path)
        filename_prefix = _safe_filename_prefix(filename_prefix, default="transparent")
        prompt = _unpack(prompt)
        extra_pnginfo = _unpack(extra_pnginfo)

        source_slots = _collect_source_slots(image_urls)
        url_rgba_list = _download_source_slots(source_slots) if source_slots else []
        target_size = _reference_canvas_size(reference_image)
        layer_names = _layer_names_from_plan(layer_plan_json, len(url_rgba_list))
        layer_records = _layer_records_from_plan(layer_plan_json, len(url_rgba_list))
        background_index = _background_layer_index(layer_names)
        if background_index is None:
            inferred_names = _infer_split_layer_names_from_prompt(prompt, len(url_rgba_list))
            inferred_background_index = _background_layer_index(inferred_names)
            if inferred_background_index is not None:
                layer_names = inferred_names
                background_index = inferred_background_index
                print("[SynVowTransparentSave] 已从工作流自动识别参考图分层顺序，无需额外连接 layer_plan_json")
        direct_split_output = background_index is not None
        geometry_adjusted_count = 0
        geometry_plan_available = any(_planned_layer_bbox(record) for record in layer_records)
        if direct_split_output and geometry_plan_available and target_size and url_rgba_list:
            normalized_layers, split_canvas_size, geometry_adjusted_count = _normalize_split_rgba_layers(
                url_rgba_list,
                layer_records,
                background_index,
                target_size,
            )
            for image in url_rgba_list:
                if image is not None:
                    image.close()
            url_rgba_list = normalized_layers
            target_size = split_canvas_size
        checkerboard_repaired_count = 0
        if not direct_split_output:
            for index, image in enumerate(url_rgba_list):
                if image is None or _has_real_alpha(image):
                    continue
                repaired, repair_info = _repair_fake_checkerboard_alpha(image)
                if repair_info:
                    image.close()
                    url_rgba_list[index] = repaired
                    checkerboard_repaired_count += 1
                    print(f"[SynVowTransparentSave] 棋盘格假透明已转 Alpha ({index + 1}): {repair_info}")

        normalized_count = 0
        if target_size and not direct_split_output:
            for index, image in enumerate(url_rgba_list):
                if image is not None and image.size != target_size:
                    mode = "cover" if index == background_index else "contain"
                    fitted = _fit_rgba_to_size(image, target_size, mode=mode)
                    image.close()
                    url_rgba_list[index] = fitted
                    normalized_count += 1
        valid_url_rgba = [img for img in url_rgba_list if img is not None]
        if direct_split_output and valid_url_rgba:
            width, height = valid_url_rgba[0].size
        else:
            width, height = target_size or (valid_url_rgba[0].size if valid_url_rgba else DEFAULT_PLACEHOLDER_SIZE)
        source_rgba_list = url_rgba_list if source_slots else [None]

        if is_absolute_save:
            full_output_folder = os.path.abspath(raw_save_path)
            os.makedirs(full_output_folder, exist_ok=True)
            filename = filename_prefix
            counter = _next_counter(full_output_folder, filename)
            subfolder = ""
            preview_folder, preview_filename, preview_counter, preview_subfolder, _ = folder_paths.get_save_image_path(
                f"SynVowTransparentPreview/{filename_prefix}",
                self.output_dir,
                width,
                height,
            )
        else:
            relative_save_path = _safe_relative_path(raw_save_path, default="SynVowTransparent")
            output_prefix = f"{relative_save_path}/{filename_prefix}" if relative_save_path else filename_prefix
            full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(
                output_prefix,
                self.output_dir,
                width,
                height,
            )
            preview_folder = None
            preview_filename = None
            preview_counter = None
            preview_subfolder = None

        metadata = None
        if not args.disable_metadata:
            metadata = PngInfo()
            if prompt is not None:
                metadata.add_text("prompt", json.dumps(prompt))
            if isinstance(extra_pnginfo, dict):
                for key in extra_pnginfo:
                    metadata.add_text(key, json.dumps(extra_pnginfo[key]))

        ui_results = []
        saved_tensors = []
        rgba_paths = []
        alpha_count = 0
        url_saved_count = 0
        placeholder_count = 0

        for batch_number, rgba in enumerate(source_rgba_list):
            if rgba is None:
                rgba = Image.new("RGBA", (width, height), (0, 0, 0, 255))
                placeholder_count += 1
                print(f"[SynVowTransparentSave] 第 {batch_number + 1} 张无可用 URL，使用 {width}x{height} 黑图占位")
            else:
                rgba = rgba.convert("RGBA")
                url_saved_count += 1
            has_alpha = _has_real_alpha(rgba)
            if has_alpha:
                alpha_count += 1

            filename_with_batch_num = filename.replace("%batch_num%", str(batch_number))
            rgba_path, rgba_file, counter = _next_available_png_path(full_output_folder, filename_with_batch_num, counter)
            rgba.save(rgba_path, pnginfo=metadata, compress_level=self.compress_level)
            rgba_paths.append(rgba_path)
            saved_tensors.append(_rgba_pil_to_tensor(rgba))

            if is_absolute_save:
                preview_name = preview_filename.replace("%batch_num%", str(batch_number))
                ui_filename = f"{preview_name}_{preview_counter:05}_alpha.png"
                preview_path = os.path.join(preview_folder, ui_filename)
                rgba.save(preview_path, pnginfo=metadata, compress_level=self.compress_level)
                ui_subfolder = preview_subfolder
                preview_counter += 1
            else:
                ui_filename = rgba_file
                ui_subfolder = subfolder

            ui_results.append({
                "filename": ui_filename,
                "subfolder": ui_subfolder,
                "type": self.type,
            })
            counter += 1

        display_folder = full_output_folder if is_absolute_save else (subfolder or ".")
        status = (
            f"已保存 {len(rgba_paths)} 张 RGBA PNG；检测到透明像素 {alpha_count}/{len(rgba_paths)}；"
            f"棋盘格假透明修复 {checkerboard_repaired_count}/{len(rgba_paths)}；"
            f"URL原图保存 {url_saved_count}/{len(rgba_paths)}；保存目录 {display_folder}。"
        )
        if is_absolute_save:
            status += " 已在 ComfyUI output/SynVowTransparentPreview 生成同 alpha 预览副本。"
        if placeholder_count:
            status += f" 上游失败黑图占位 {placeholder_count}/{len(rgba_paths)}，工作流已继续。"
        if url_saved_count and alpha_count == 0:
            status += " 注意：未检测到透明像素，请检查上游 URL 是否是带 alpha 的 PNG。"
        if direct_split_output:
            if geometry_adjusted_count:
                status += (
                    f" 参考图分层模式：背景已铺满并强制不透明，按LLM坐标归位 {geometry_adjusted_count}/{len(rgba_paths)} 层；"
                    "未生成新蒙版、未套回原图像素。"
                )
            else:
                status += " 参考图分层模式：未连接有效 asset_plan_json，已原样保存 Image 2.5 返回的 RGBA PNG。"
        elif target_size:
            status += (
                f" 已按参考图画布归一化 {normalized_count}/{len(rgba_paths)} 张，"
                f"目标尺寸 {target_size[0]}x{target_size[1]}。"
            )
        return {
            "ui": {"images": ui_results},
            "result": (saved_tensors, "\n".join(rgba_paths), status),
        }


NODE_CLASS_MAPPINGS = {
    "SynVowTransparentPngSavePreview": SynVowTransparentPngSavePreview,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SynVowTransparentPngSavePreview": "SynVow 透明PNG保存预览",
}
