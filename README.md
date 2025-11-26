# SynVow-Prompt

🛍️ **E-Commerce Prompt Generator** - A ComfyUI custom node for generating AI-powered e-commerce product prompts using Google Gemini.

## ✨ Features

- **AI-Powered Prompt Generation**: Automatically generates creative product descriptions and prompts for e-commerce images using Google Gemini API
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
   `ash
   cd ComfyUI/custom_nodes
   `

2. Clone this repository:
   `ash
   git clone https://github.com/YOUR_USERNAME/SynVow-prompt.git
   `

3. Install dependencies:
   `ash
   cd SynVow-prompt
   pip install -r requirements.txt
   `

4. Restart ComfyUI

### Method 2: Manual Installation

1. Download this repository as ZIP
2. Extract to `ComfyUI/custom_nodes/SynVow-prompt`
3. Install required packages: `google-generativeai`
4. Restart ComfyUI

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
- Google Gemini API key
- Required Python packages: `google-generativeai`

## ⚙️ Configuration

The node uses the Google Gemini API for prompt generation. You'll need:
- A valid Google Gemini API key
- Internet connection for API access

## 🔧 Node Details

### EcommercePromptGenerator

**Category**: `SynVow`

**Inputs:**
- `product_name` (STRING): The name of your product
- `product_description` (STRING, multiline): Detailed description of the product
- `design_style` (COMBO): Predefined design styles dropdown
- `seed` (INT): Seed value for reproducible generation (range: 0-99999, default: 0)

**Outputs:**
- `prompt` (STRING): Generated detailed prompt for image generation
- `main_copy` (STRING): Main marketing copy text
- `sub_copy` (STRING): Secondary marketing copy text

## 🎨 Available Design Styles

The node includes 20+ carefully curated design styles:
- 极简主义, 赛博朋克, 复古风格, 未来科技
- 自然有机, 工业风格, 北欧风格, 日式和风
- 波普艺术, 新艺术运动, 包豪斯, 孟菲斯
- 蒸汽波, 哥特式, 装饰艺术, 野兽派
- 超现实主义, 立体主义, 抽象表现主义, 极繁主义

## 📝 License

MIT License

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 💬 Support

For issues and questions, please open an issue on GitHub.

## 🙏 Acknowledgments

- Built for [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- Powered by Google Gemini API

---

Made with ❤️ by SynVow
