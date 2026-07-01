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


def _collect_urls(value) -> List[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    urls = []
    for item in items:
        if item is None:
            continue
        text = str(item)
        for url in re.findall(r"https?://[^\s\"'<>]+", text):
            cleaned = url.rstrip("),，。；;")
            if cleaned and cleaned not in urls:
                urls.append(cleaned)
    return urls


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


def _rgba_pil_to_tensor(image: Image.Image) -> torch.Tensor:
    array = np.asarray(image.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


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


def _repair_fake_checkerboard_alpha(image: Image.Image) -> tuple:
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
    if spread < 12 or light_ratio < 0.08 or mid_ratio < 0.08:
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
    DESCRIPTION = "从 image_urls 下载原始 RGBA PNG，并保存真实 Alpha 通道透明图。"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return random.random()

    def save(
        self,
        image_urls,
        save_path="SynVowTransparent",
        filename_prefix="transparent",
        prompt=None,
        extra_pnginfo=None,
    ):
        raw_save_path = _raw_path(save_path, default="SynVowTransparent")
        is_absolute_save = _is_absolute_save_path(raw_save_path)
        filename_prefix = _safe_filename_prefix(filename_prefix, default="transparent")
        prompt = _unpack(prompt)
        extra_pnginfo = _unpack(extra_pnginfo)

        url_list = _collect_urls(image_urls)
        url_rgba_list = _download_rgba_images(url_list) if url_list else []
        valid_url_rgba = [img for img in url_rgba_list if img is not None]

        if not valid_url_rgba:
            raise ValueError("没有收到可下载的 image_urls，或 URL 下载失败。")

        width, height = valid_url_rgba[0].size

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
        checkerboard_repaired_count = 0
        url_saved_count = 0

        for batch_number in range(len(url_rgba_list)):
            rgba = url_rgba_list[batch_number] if batch_number < len(url_rgba_list) else None
            if rgba is None:
                continue
            rgba = rgba.convert("RGBA")
            repair_info = ""
            if not _has_real_alpha(rgba):
                rgba, repair_info = _repair_fake_checkerboard_alpha(rgba)
                if repair_info:
                    checkerboard_repaired_count += 1
                    print(f"[SynVowTransparentSave] 棋盘格假透明已转 Alpha ({batch_number + 1}): {repair_info}")
            has_alpha = _has_real_alpha(rgba)
            url_saved_count += 1
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
        if alpha_count == 0:
            status += " 注意：未检测到透明像素，请检查上游 URL 是否是带 alpha 的 PNG。"

        return {
            "ui": {"images": ui_results},
            "result": (saved_tensors, "\n".join(rgba_paths), status),
        }


NODE_CLASS_MAPPINGS = {
    "SynVowPromptTransparentPngSavePreview": SynVowTransparentPngSavePreview,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SynVowPromptTransparentPngSavePreview": "SynVow 透明PNG保存预览 (RH)",
}
