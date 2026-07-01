from .prompt_nodes import EcommercePromptGenerator, ListToBatchConverter
from .banana_ecommerce_prompt_v3 import NODE_CLASS_MAPPINGS as BANANA_ECOMMERCE_MAPPINGS
from .banana_ecommerce_prompt_v3 import NODE_DISPLAY_NAME_MAPPINGS as BANANA_ECOMMERCE_DISPLAY
from .utils import SynVowLLMSettings
from .txt2img_prompt_optimizer import NODE_CLASS_MAPPINGS as TXT2IMG_MAPPINGS
from .txt2img_prompt_optimizer import NODE_DISPLAY_NAME_MAPPINGS as TXT2IMG_DISPLAY
from .img2img_prompt_optimizer import NODE_CLASS_MAPPINGS as IMG2IMG_MAPPINGS
from .img2img_prompt_optimizer import NODE_DISPLAY_NAME_MAPPINGS as IMG2IMG_DISPLAY
from .longscroll_detail_page import NODE_CLASS_MAPPINGS as LONGSCROLL_DETAIL_MAPPINGS
from .longscroll_detail_page import NODE_DISPLAY_NAME_MAPPINGS as LONGSCROLL_DETAIL_DISPLAY
from .transparent_asset_generator import NODE_CLASS_MAPPINGS as TRANSPARENT_ASSET_MAPPINGS
from .transparent_asset_generator import NODE_DISPLAY_NAME_MAPPINGS as TRANSPARENT_ASSET_DISPLAY
from .gpt_image_2_alpha_runninghub import NODE_CLASS_MAPPINGS as RH_GPT_IMAGE2_ALPHA_MAPPINGS
from .gpt_image_2_alpha_runninghub import NODE_DISPLAY_NAME_MAPPINGS as RH_GPT_IMAGE2_ALPHA_DISPLAY
from .transparent_png_save_preview import NODE_CLASS_MAPPINGS as TRANSPARENT_SAVE_MAPPINGS
from .transparent_png_save_preview import NODE_DISPLAY_NAME_MAPPINGS as TRANSPARENT_SAVE_DISPLAY

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {
    "SynVowLLMSettings": SynVowLLMSettings,
    "EcommercePromptGenerator": EcommercePromptGenerator,
    "ListToBatchConverter": ListToBatchConverter,
    **BANANA_ECOMMERCE_MAPPINGS,
    **TXT2IMG_MAPPINGS,
    **IMG2IMG_MAPPINGS,
    **LONGSCROLL_DETAIL_MAPPINGS,
    **TRANSPARENT_ASSET_MAPPINGS,
    **RH_GPT_IMAGE2_ALPHA_MAPPINGS,
    **TRANSPARENT_SAVE_MAPPINGS,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SynVowLLMSettings": "SynVow LLM Settings",
    "EcommercePromptGenerator": "SynVow详情页提示词生成器",
    "ListToBatchConverter": "🔄 List to Batch Converter",
    **BANANA_ECOMMERCE_DISPLAY,
    **TXT2IMG_DISPLAY,
    **IMG2IMG_DISPLAY,
    **LONGSCROLL_DETAIL_DISPLAY,
    **TRANSPARENT_ASSET_DISPLAY,
    **RH_GPT_IMAGE2_ALPHA_DISPLAY,
    **TRANSPARENT_SAVE_DISPLAY,
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
