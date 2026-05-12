from .prompt_nodes import EcommercePromptGenerator, ListToBatchConverter
from .utils import SynVowLLMSettings
from .txt2img_prompt_optimizer import NODE_CLASS_MAPPINGS as TXT2IMG_MAPPINGS
from .txt2img_prompt_optimizer import NODE_DISPLAY_NAME_MAPPINGS as TXT2IMG_DISPLAY
from .img2img_prompt_optimizer import NODE_CLASS_MAPPINGS as IMG2IMG_MAPPINGS
from .img2img_prompt_optimizer import NODE_DISPLAY_NAME_MAPPINGS as IMG2IMG_DISPLAY

NODE_CLASS_MAPPINGS = {
    "SynVowLLMSettings": SynVowLLMSettings,
    "EcommercePromptGenerator": EcommercePromptGenerator,
    "ListToBatchConverter": ListToBatchConverter,
    **TXT2IMG_MAPPINGS,
    **IMG2IMG_MAPPINGS,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SynVowLLMSettings": "SynVow LLM Settings",
    "EcommercePromptGenerator": "SynVow详情页提示词生成器",
    "ListToBatchConverter": "🔄 List to Batch Converter",
    **TXT2IMG_DISPLAY,
    **IMG2IMG_DISPLAY,
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
