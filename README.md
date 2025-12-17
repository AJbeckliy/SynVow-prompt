# SynVow-Prompt

🛍️ **E-Commerce Prompt Generator** - A ComfyUI custom node for generating AI-powered e-commerce product prompts using any OpenAI-compatible API (including Google Gemini, OpenAI, Claude, etc.).

## ✨ Features

- **AI-Powered Prompt Generation**: Automatically generates creative product descriptions and prompts for e-commerce images using any OpenAI-compatible API
- **Customizable Parameters**: 
  - Product name and description input
  - Design style selection (dropdown menu with 20+ predefined styles)
  - Seed control for reproducible results (0-99999)
  - Language support (Chinese/English with automatic detection)
- **Rich Output**: Generates main copy, sub-copy, and detailed prompts
- **Seamless ComfyUI Integration**: Works perfectly within the ComfyUI workflow

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

1. In ComfyUI, find the **🛍️ E-Commerce Prompt Generator (Gemini)** node in the node menu
2. Configure the parameters:
   - **product_name**: Enter your product name (e.g., "智能手表")
   - **product_description**: Provide a brief product description
   - **design_style**: Select from 20+ predefined design styles
   - **seed**: Set a seed value (0-99999) for reproducible results
3. Connect the output to your image generation nodes

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
- `seed` (INT): Seed value for reproducible generation (range: 0-99999)
- `prompt_count` (INT): Number of screens to generate (1-20, default: 10)
- `product_image` (IMAGE, optional): Product image for visual reference

**Outputs:**
- `prompts_list` (STRING[]): List of generated prompts for each screen
- `debug_info` (STRING): Debug information including raw API response

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
