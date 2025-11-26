from .nodes import EcommercePromptGenerator

NODE_CLASS_MAPPINGS = {
    "EcommercePromptGenerator": EcommercePromptGenerator
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "EcommercePromptGenerator": "SynVow详情页提示词生成器"
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]