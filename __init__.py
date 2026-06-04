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

NODE_CLASS_MAPPINGS = {
    "SynVowLLMSettings": SynVowLLMSettings,
    "EcommercePromptGenerator": EcommercePromptGenerator,
    "ListToBatchConverter": ListToBatchConverter,
    **BANANA_ECOMMERCE_MAPPINGS,
    **TXT2IMG_MAPPINGS,
    **IMG2IMG_MAPPINGS,
    **LONGSCROLL_DETAIL_MAPPINGS,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SynVowLLMSettings": "SynVow LLM Settings",
    "EcommercePromptGenerator": "SynVow详情页提示词生成器",
    "ListToBatchConverter": "🔄 List to Batch Converter",
    **BANANA_ECOMMERCE_DISPLAY,
    **TXT2IMG_DISPLAY,
    **IMG2IMG_DISPLAY,
    **LONGSCROLL_DETAIL_DISPLAY,
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
