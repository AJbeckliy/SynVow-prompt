# SynVow-Prompt

🛍️ **SynVow 提示词工具集（v1.4）** - ComfyUI 自定义节点：提供电商详情页多屏提示词生成、香蕉电商详情页 V3（带参考图）、文生图提示词优化、图生图参考提示词优化等功能。默认支持 RunningHub LLM 封装，也可通过 `SynVow LLM Settings` 接入任意 OpenAI-compatible 接口。

## ✨ Features

- **电商详情页多屏生成**：保留原版 `SynVow 详情页提示词生成器`，支持 `product_image` + `product_image_2/3/4` 多张参考图。
- **香蕉电商详情页 V3（带参考图）**：新增 `香蕉电商详情页提示词生成器V3-带参考图`，支持 8 张产品参考图 + 4 张风格参考图，严格区分产品外观参考和风格参考。
- **文生图提示词控制器**：双 LLM Schema 流程，节点内置 RunningHub `model` 下拉框，支持版式选择、文字策略（不加/保留/优化/自动生成）、优化强度等精细控制。
- **图生图提示词控制器**：基于参考图 + 可选主体图，节点内置 RunningHub `model` 下拉框，支持风格/构图/色彩/版式等多维度参考模式。
- **RH GPT-image2 长卷详情页工作流**：新增 4 个 RunningHub 版详情页节点，支持规划 → 页面结构 → 批量生图提示词 → 长图拼接，适合 9:21 多屏电商详情页。
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

### RH GPT-image2 长卷详情页工作流
节点位于 **SynVow-prompt / RH详情页** 分类下，建议按下面顺序连接：

1. `RH GPT-image2详情页规划`
   - 输入产品图、参考图、产品名称、产品品类、卖点/文案/设计补充、切片数量。
   - 输出 `叙事结构_JSON`、`长卷视觉母版说明`、`叙事结构_Markdown`。
2. `RH GPT-image2详情页结构`
   - 接入规划节点输出的 `叙事结构_JSON` 和 `长卷视觉母版说明`。
   - 输出每一屏的页面结构蓝图。
3. `RH GPT-image2详情页批量提示词`
   - 接入页面结构蓝图和视觉母版说明。
   - 输出 `提示词列表`（STRING[]），可直接接批量生图节点。
4. `RH 详情页图像列表顺序拼接长图`
   - 接入生图后的 `IMAGE` 列表。
   - 自动按第一张图宽度统一缩放，并按列表顺序竖向拼接成长图。

> 建议：主要卖点、产品信息和风格诉求优先写在规划节点的 `卖点_文案_设计补充`。结构节点和批量提示词节点的修正输入只用于局部调整，不建议重复填写核心卖点。

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

### RH GPT-image2详情页规划（SynVowPromptLongScrollNarrativePlanner）

| 参数 | 类型 | 说明 |
|------|------|------|
| `产品图_1` | IMAGE | 主产品图，必填，用于锁定产品外观 |
| `模型` | COMBO | RunningHub LLM 模型下拉框 |
| `产品名称` | STRING | 产品名称 |
| `产品品类` | STRING | 产品品类 |
| `卖点_文案_设计补充` | STRING | 核心卖点、文案方向、设计参考或页面结构诉求 |
| `切片数量` | INT | 详情页屏数，当前上限 10 |
| `种子` | INT | 随机种子 |
| `llm_config` | SYNVOW_LLM_CONFIG（可选） | 第三方接口配置，连接后覆盖 RunningHub 默认配置 |
| `temperature` | FLOAT（可选） | LLM 发散程度 |
| `产品图_2` ~ `产品图_4` | IMAGE（可选） | 更多产品参考图 |
| `参考图_1` ~ `参考图_4` | IMAGE（可选） | 风格、版式、场景参考图 |

**输出**：`叙事结构_JSON`、`长卷视觉母版说明`、`叙事结构_Markdown`、`生成状态`

### RH GPT-image2详情页结构（SynVowPromptLongScrollPageStructurePlanner）

| 参数 | 类型 | 说明 |
|------|------|------|
| `叙事结构_JSON` | STRING | 来自规划节点 |
| `长卷视觉母版说明` | STRING | 来自规划节点 |
| `模型` | COMBO | RunningHub LLM 模型下拉框 |
| `结构修正要求_可选` | STRING（可选） | 局部结构修正，不建议重复输入主要卖点 |
| `llm_config` | SYNVOW_LLM_CONFIG（可选） | 第三方接口配置 |
| `temperature` | FLOAT（可选） | LLM 发散程度 |
| `种子` | INT（可选） | 随机种子 |

**输出**：`页面结构蓝图_JSON`、`页面结构蓝图_Markdown`、`生成状态`

### RH GPT-image2详情页批量提示词（SynVowPromptLongScrollPromptBatchBuilder）

| 参数 | 类型 | 说明 |
|------|------|------|
| `页面结构蓝图_JSON` | STRING | 来自结构节点 |
| `长卷视觉母版说明` | STRING | 来自规划节点 |
| `模型` | COMBO | RunningHub LLM 模型下拉框 |
| `叙事结构_JSON` | STRING（可选） | 来自规划节点，用于补充上下文 |
| `出图提示词修正_可选` | STRING（可选） | 局部生图提示词修正 |
| `llm_config` | SYNVOW_LLM_CONFIG（可选） | 第三方接口配置 |
| `temperature` | FLOAT（可选） | LLM 发散程度 |
| `种子` | INT（可选） | 随机种子 |

**输出**：`批量提示词_JSON`、`批量提示词_文本`、`提示词列表`（STRING[]）、`生成状态`

### RH 详情页图像列表顺序拼接长图（SynVowPromptLongScrollImageListConcat）

| 参数 | 类型 | 说明 |
|------|------|------|
| `图像列表` | IMAGE | 多张详情页切片图像列表 |

**输出**：`长图`、`拼接状态`

拼接逻辑固定为：按第一张图宽度统一缩放，按列表顺序竖向拼接，不裁剪重叠区域。

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
