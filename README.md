# SynVow-Prompt

🛍️ **SynVow 提示词工具集（v1.4）** - ComfyUI 自定义节点：提供电商详情页多屏提示词生成、香蕉电商详情页 V3（带参考图）、文生图提示词优化、图生图参考提示词优化等功能。默认支持 RunningHub LLM 封装，也可通过 `SynVow LLM Settings` 接入任意 OpenAI-compatible 接口。

## ✨ Features

- **电商详情页多屏生成**：保留原版 `SynVow 详情页提示词生成器`，支持 `product_image` + `product_image_2/3/4` 多张参考图。
- **香蕉电商详情页 V3（带参考图）**：新增 `香蕉电商详情页提示词生成器V3-带参考图`，支持 8 张产品参考图 + 4 张风格参考图，严格区分产品外观参考和风格参考。
- **文生图提示词控制器**：双 LLM Schema 流程，节点内置 RunningHub `model` 下拉框，支持版式选择、文字策略（不加/保留/优化/自动生成）、优化强度等精细控制。
- **图生图提示词控制器**：基于参考图 + 可选主体图，节点内置 RunningHub `model` 下拉框，支持风格/构图/色彩/版式等多维度参考模式。
- **可控场景偏好**：提供 `scene_preference`（混合/生活方式交互/棚拍干净背景）。
- **严格列表输出**：输出为 `STRING[]`（列表），每个元素对应一屏完整提示词，可直接接到批量生图流程。
- **RunningHub + 第三方双通道**：默认使用 RunningHub LLM 请求方式；需要第三方接口时，连接 `SynVow LLM Settings` 作为备用配置。

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

所有节点位于 ComfyUI 节点菜单的 **SynVow-prompt** 分类下。

### SynVow 详情页提示词生成器
1. 填写 `api_url`、`api_key`、`model_name`
2. 设置 `product_type`、`selling_points`、`design_style`、`scene_preference`、`prompt_count`
3. （可选）连接参考图：`product_image` ~ `product_image_4`
4. 输出 `prompts_list`（多屏提示词列表），可直接对接批量生图流程

### 香蕉电商详情页提示词生成器V3-带参考图
1. 选择 `model`（RunningHub 模型下拉框）
2. 设置 `product_type`、`selling_points`、`design_style`、`scene_preference`、`output_language`、`prompt_count`
3. （可选）连接产品参考图：`product_image_1` ~ `product_image_8`
4. （可选）连接风格参考图：`ref_image_1` ~ `ref_image_4`
5. （可选）连接 `SynVow LLM Settings` 的 `llm_config`，使用第三方 OpenAI-compatible 接口
6. 输出 `prompts_list`、`prompts_count`、`debug_info`

### SynVow-文生图提示词控制器
1. 输入 `user_prompt`，选择 `model`、`layout_type`、`text_policy`、`optimize_strength`、`aspect_ratio`
2. 默认走 RunningHub LLM 封装；如需第三方接口，连接 `SynVow LLM Settings` 的 `llm_config`
3. （可选）填写 `exact_text` 指定画面文字
4. 输出 `optimized_prompt` + `debug_info`

### SynVow-图生图提示词控制器
1. 连接 `reference_image`，选择 `model`、`reference_mode` 和 `target_aspect_ratio`
2. 默认走 RunningHub LLM 封装；如需第三方接口，连接 `SynVow LLM Settings` 的 `llm_config`
3. （可选）连接 `subject_image`（主体图）
4. 输出 `optimized_prompt` + `reference_summary`

### SynVow LLM Settings（第三方备用）
1. 填写第三方 OpenAI-compatible 接口的 `base_url`、`apikey`、`model_name`
2. 将 `llm_config` 连接到香蕉 V3、文生图或图生图控制器
3. 连接后，节点会优先使用这里的第三方配置；不连接则使用 RunningHub 默认封装

## 📋 Requirements

- ComfyUI
- Python 3.8+
- `requests`、`urllib3`（文生图/图生图控制器依赖，安装后自动满足）
- RunningHub 环境或支持 RunningHub LLM 的 shared/enterprise API Key
- 如使用第三方接口，则需要一个 OpenAI-compatible LLM 服务的 API Key

## 🔧 Node Details

所有节点 **Category**: `SynVow-prompt`

### SynVow 详情页提示词生成器（EcommercePromptGenerator）

| 参数 | 类型 | 说明 |
|------|------|------|
| `api_url` | STRING | API 地址（如 `https://api.openai.com/v1`） |
| `api_key` | STRING | API Key |
| `model_name` | STRING | 模型名 |
| `product_type` | STRING | 产品类型 |
| `selling_points` | STRING | 核心卖点 |
| `design_style` | COMBO | 设计风格（9 种预设） |
| `scene_preference` | COMBO | 场景偏好 |
| `output_language` | COMBO | 输出语言 |
| `prompt_count` | INT | 生成屏数（1-20） |
| `product_image` ~ `product_image_4` | IMAGE（可选） | 产品参考图 |

**输出**：`prompts_list`（STRING[] 多屏提示词）、`debug_info`

### 香蕉电商详情页提示词生成器V3-带参考图（BananaEcommercePromptGeneratorV3）

| 参数 | 类型 | 说明 |
|------|------|------|
| `model` | COMBO | RunningHub LLM 模型下拉框 |
| `product_type` | STRING | 产品类型 |
| `selling_points` | STRING | 核心卖点 |
| `design_style` | COMBO | 设计风格（9 种预设） |
| `scene_preference` | COMBO | 场景偏好 |
| `output_language` | COMBO | 输出语言 |
| `seed` | INT | 随机种子 |
| `prompt_count` | INT | 生成屏数（1-20） |
| `llm_config` | SYNVOW_LLM_CONFIG（可选） | 第三方接口配置，连接后覆盖 RunningHub 默认配置 |
| `product_image_1` ~ `product_image_8` | IMAGE（可选） | 产品参考图，用于锁定产品外观 |
| `ref_image_1` ~ `ref_image_4` | IMAGE（可选） | 风格参考图，用于参考色调、光影、构图与排版 |

**输出**：`prompts_list`（STRING[] 多屏提示词）、`prompts_count`、`debug_info`

### SynVow-文生图提示词控制器（RHTxt2ImgPromptOptimizer）

| 参数 | 类型 | 说明 |
|------|------|------|
| `user_prompt` | STRING | 用户描述 |
| `model` | COMBO | RunningHub LLM 模型下拉框 |
| `llm_config` | SYNVOW_LLM_CONFIG（可选） | 第三方接口配置，连接后覆盖 RunningHub 默认配置 |
| `layout_type` | COMBO | 版式（自动判断/纯画面/图文混排海报/电商主图/社媒封面） |
| `text_policy` | COMBO | 文字策略（不加/保留/优化/自动生成） |
| `optimize_strength` | COMBO | 优化强度（标准/增强） |
| `aspect_ratio` | COMBO | 画面比例 |
| `exact_text` | STRING | 指定画面文字 |

**输出**：`optimized_prompt`、`debug_info`

### SynVow-图生图提示词控制器（RHImg2ImgPromptOptimizer）

| 参数 | 类型 | 说明 |
|------|------|------|
| `reference_image` | IMAGE | 参考图 |
| `user_prompt` | STRING | 用户描述 |
| `model` | COMBO | RunningHub LLM 模型下拉框 |
| `llm_config` | SYNVOW_LLM_CONFIG（可选） | 第三方接口配置，连接后覆盖 RunningHub 默认配置 |
| `reference_mode` | COMBO | 参考模式（自动/综合/风格/构图/色彩光影/版式） |
| `target_aspect_ratio` | COMBO | 目标画面比例 |
| `subject_image` | IMAGE（可选） | 主体图 |

**输出**：`optimized_prompt`、`reference_summary`

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
