from .prompt_nodes import EcommercePromptGenerator, ListToBatchConverter

NODE_CLASS_MAPPINGS = {
    "EcommercePromptGenerator": EcommercePromptGenerator,
    "ListToBatchConverter": ListToBatchConverter
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "EcommercePromptGenerator": "SynVow详情页提示词生成器",
    "ListToBatchConverter": "🔄 List to Batch Converter"
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]