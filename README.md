# SynVow-Prompt

🛍️ **SynVow 详情页提示词生成器（v1.2）** - ComfyUI 自定义节点：使用任意 OpenAI-compatible 的多模态接口（支持图片输入）生成电商详情页多屏提示词。

## ✨ Features

- **多图参考增强一致性**：支持 `product_image` + `product_image_2/3/4` 多张参考图（同一商品不同角度/细节），提升主体一致性。
- **仅锁定主体、重建新场景**：参考图只用于锁定产品/人物外观，忽略原背景；自动生成更吸引人的使用/穿搭/特写等新场景。
- **可控场景偏好**：提供 `scene_preference`（混合/生活方式交互/棚拍干净背景）。
- **严格列表输出**：输出为 `STRING[]`（列表），每个元素对应一屏完整提示词，可直接接到批量生图流程。
- **兼容 OpenAI Chat Completions 接口**：支持自定义 `api_url`、`model_name`，适配 Gemini/OpenAI/其他兼容服务。

## 📦 Installation

### Method 1: Git Clone (Recommended)

1. Navigate to your ComfyUI custom nodes directory:
   ```bash
   cd ComfyUI/custom_nodes
   ```

2. Clone this repository:
   ```bash
   git clone https://github.com/AJbeckliy/SynVow-prompt.git
   ```

3. Restart ComfyUI (no additional dependencies required)

### Method 2: Manual Installation

1. Download this repository as ZIP
2. Extract to `ComfyUI/custom_nodes/SynVow-prompt`
3. Restart ComfyUI (no additional dependencies required)

## 🚀 Usage

1. 在 ComfyUI 节点菜单中找到：`SynVow详情页提示词生成器`
2. 填写参数：
   - `api_url`：你的 OpenAI-compatible 接口地址（例如 `https://api.openai.com/v1` 或第三方代理地址）
   - `api_key`：你的 API Key（不会写入仓库）
   - `model_name`：模型名（需支持图片输入才能使用参考图）
   - `product_type` / `selling_points`：产品类型与核心卖点
   - `design_style`：页面风格
   - `scene_preference`：场景偏好（推荐默认“混合（以使用场景为主）”）
   - `prompt_count`：输出多少屏
3.（可选但推荐）连接多张参考图：`product_image`、`product_image_2`、`product_image_3`、`product_image_4`
4. 输出 `prompts_list` 是一个列表（多屏提示词），可直接对接批量生图节点或你自己的批处理流程

## 📋 Requirements

- ComfyUI
- Python 3.8+
- An API key for any OpenAI-compatible LLM service (e.g., OpenAI, Google Gemini, Anthropic Claude, etc.)
- No additional Python packages required (uses Python standard library)

## ⚙️ Configuration

The node uses any OpenAI-compatible API for prompt generation. You'll need:
- A valid API key for your chosen LLM service
- The API endpoint URL (e.g., `https://api.openai.com/v1` or your custom endpoint)
- Internet connection for API access

## 🔧 Node Details

### EcommercePromptGenerator

**Category**: `🛒 E-Commerce AI/Prompting`

**Inputs:**
- `api_url` (STRING): API endpoint URL (default: `https://api.openai.com/v1`)
- `api_key` (STRING): Your API key
- `model_name` (STRING): Model name (default: `gemini-2.0-flash-exp`)
- `product_type` (STRING): The type of your product (e.g., "美妆粉底液")
- `selling_points` (STRING, multiline): Core selling points of the product
- `design_style` (COMBO): Predefined design styles dropdown
- `scene_preference` (COMBO): 场景偏好（生活方式交互/棚拍干净背景/混合）
- `output_language` (COMBO): 输出语言（中文/英文/自动检测）
- `seed` (INT): Seed value for reproducible generation (range: 0-99999)
- `prompt_count` (INT): Number of screens to generate (1-20, default: 10)
- `product_image` (IMAGE, optional): 参考图 1
- `product_image_2` (IMAGE, optional): 参考图 2
- `product_image_3` (IMAGE, optional): 参考图 3
- `product_image_4` (IMAGE, optional): 参考图 4

**Outputs:**
- `prompts_list` (STRING[]): 多屏提示词列表（一个元素=一屏完整提示词）
- `debug_info` (STRING): 调试信息（包含原始模型输出）

## 🎨 Available Design Styles

The node includes 9 carefully curated design styles:
- 简约 Ins 风, 高级奢华, 科技感, 清新自然
- 国潮风, 活泼撞色, 极简工业风, 梦幻唯美
- 亚马逊风格

## 📝 License

MIT License

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 💬 Support

For issues and questions, please open an issue on GitHub.

## 🙏 Acknowledgments

- Built for [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- Supports any OpenAI-compatible API

---

Made with ❤️ by SynVow
