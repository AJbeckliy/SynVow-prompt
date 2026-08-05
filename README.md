# SynVow-Prompt

[![ComfyUI](https://img.shields.io/badge/ComfyUI-Custom_Nodes-111111)](https://github.com/comfyanonymous/ComfyUI)
[![RunningHub](https://img.shields.io/badge/RunningHub-API-6C5CE7)](https://www.runninghub.cn/)
[![GPT--Image--2](https://img.shields.io/badge/GPT--Image--2-Product_Studio-10A37F)](https://github.com/AJbeckliy/SynVow-prompt)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

🛍️ **SynVow 提示词与电商视觉工具集（v1.7）** —— 面向 ComfyUI 的 RunningHub 图像生成与提示词工作流，覆盖产品精修、功能科技特效、Mask 局部编辑、白边扩图、电商详情页、透明素材和多模态提示词优化。

## 🆕 v1.7：RunningHub H3 多参考提示词导演

新增一个独立的 **SynVow H3 多参考提示词导演（RunningHub）** 节点：用 RunningHub LLM 生成可直接交给 MiniMax H3 的视频提示词，只输出提示词和校验信息，不调用视频生成接口。

| 输入类型 | LLM 处理方式 | 用途 |
|---|---|---|
| 文本 / 图片_1 ~ 图片_9 | 文本和图片都会发送给视觉 LLM | 锁定人物、产品、场景、首帧或尾帧参考 |
| 视频_1 ~ 视频_3 | 不读取、不上传视频内容 | 只传连接编号与用户填写的职责 |
| 音频_1 ~ 音频_3 | 不读取、不上传音频内容 | 只传连接编号与用户填写的职责 |

节点支持文生视频、首帧图生、尾帧图生、首尾帧、多图参考和图/视频/音频多参考；同时输出英文 H3 提示词、中文导演预览、方案 JSON、媒体清单、校验报告和调试信息。

### H3 最短接线

```text
创作需求 + （可选）图片 / 视频 / 音频
                │
                ▼
SynVow H3 多参考提示词导演（RunningHub）
                │
                └── H3 英文提示词 ──▶ 你现有的 MiniMax H3 视频节点
```

- `RunningHub LLM 域名`：默认“自动（优先 `.ai`，失败回退 `.cn`）”；也可固定使用 `.ai` 或 `.cn`。
- `llm_config`：可选。连接 `SynVow LLM Settings` 后，节点使用其中的第三方 OpenAI-compatible 地址、Key 和模型，域名选择不再生效。
- `随机种子`：固定输入 + 固定种子时沿用 ComfyUI 缓存；改变创作需求、图片像素、职责文本或种子才重新调用 LLM。
- 多路视频/音频必须在职责说明中用 `视频1：...`、`音频1：...` 区分；只有一路时也支持直接填写自然语言职责。
- `音乐 MV / 情绪短片` 模式会加强全片视觉体系、人物连续性、表演、环境反应、节奏点和有动机的转场；不会假称已听过未发送的音频内容。

## 🆕 v1.6：RH GPT-Image-2 产品六合一

一个节点完成六类高频产品图片任务，直接输出 ComfyUI `IMAGE`、最终英文提示词和运行状态。

| 模式 | 主要输入 | 用途 |
|------|----------|------|
| 产品精修 | `image` | 清理瑕疵、重建材质与商业级棚拍质感 |
| 产品融入场景 | `image` + `reference_image` | 将产品自然融合到目标场景并匹配透视、光影和接触关系 |
| 模糊图片高清 | `image` | 在尽量保持原比例、构图和身份特征的前提下恢复细节 |
| 移除物品 | `image` + `mask` | 移除涂抹区域的对象并重建被遮挡背景 |
| 增加光效 | `image` + `mask` | 根据产品部件功能生成吸力、气流、扫描、感应、能量流等科技特效 |
| 扩图 | 带 `#ffffff` 外扩区域的 `image` | 自动识别与画布边缘相连的白区并延展原始环境 |

### 最短接线

```text
加载图像 ── image ──▶ RH GPT-Image-2 产品六合一 ── images ──▶ 保存图像
             mask ──▶              │
                              final_prompt / status
```

- `llm_model`：自动读取 RunningHub 模型列表；选择模型后会识别原图与 Mask 并增强提示词，选择“关闭”则使用本地英文模板。
- `model_type`：支持 RH GPT-Image-2 低价通道和官方通道。
- `aspect_ratio=auto`：根据输入画布自动选择最近的 RH 支持比例。

> [!IMPORTANT]
> 该节点调用 RunningHub 标准模型 API，需要 **Enterprise-Shared（企业共享）API Key**。普通 Key 可以上传图片，但提交 GPT-Image-2 任务时会返回错误码 `1014`；LLM 网关也只接受 SHARED/enterprise Key。

## ✨ Features

- **RH GPT-Image-2 产品六合一**：产品精修、场景融合、模糊高清、物品移除、产品功能科技特效和白边扩图；支持 Mask、视觉 LLM 提示词增强以及关闭 LLM。
- **RunningHub H3 多参考提示词导演**：单节点生成 MiniMax H3 视频提示词，支持文生视频、图生视频、首尾帧、多图、视频/音频职责映射、MV/情绪短片和输入哈希缓存。
- **电商详情页多屏生成**：保留原版 `SynVow 详情页提示词生成器`，支持 `product_image` + `product_image_2/3/4` 多张参考图。
- **香蕉电商详情页 V3（带参考图）**：新增 `香蕉电商详情页提示词生成器V3-带参考图`，支持 8 张产品参考图 + 4 张风格参考图，严格区分产品外观参考和风格参考。
- **文生图提示词控制器**：双 LLM Schema 流程，节点内置 RunningHub `model` 下拉框，支持版式选择、文字策略（不加/保留/优化/自动生成）、优化强度等精细控制。
- **图生图提示词控制器**：基于参考图 + 可选主体图，节点内置 RunningHub `model` 下拉框，支持风格/构图/色彩/版式等多维度参考模式。
- **RH GPT-image2 长卷详情页工作流**：新增 4 个 RunningHub 版详情页节点，支持规划 → 页面结构 → 批量生图提示词 → 长图拼接，适合 9:21 多屏电商详情页。
- **透明素材生成链路（RH）**：新增透明素材提示词生成器、`RH GPT-Image-2 Alpha (T_batch)` 和透明 PNG URL 保存节点，支持文生透明素材、参考图拆层、UI 图标套装、游戏道具、节日活动素材等场景。
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

### SynVow H3 多参考提示词导演（RunningHub）

1. 选择 RunningHub LLM 模型和 `RunningHub LLM 域名`；默认会优先使用 `.ai`，不可用时回退 `.cn`。
2. 填写 `创作需求`，选择任务模式、内容类型、时长、画幅、运动强度和镜头结构。
3. 文生视频不接素材；首帧/尾帧/多图模式将参考图接到对应的 `图片_1` ~ `图片_9`。
4. 有视频或音频参考时，接入 `视频_1` ~ `视频_3`、`音频_1` ~ `音频_3`，并在职责说明中写清每一路素材的用途。节点不会上传这些视频/音频内容给 LLM。
5. 将 `H3 英文提示词` 接到现有 MiniMax H3 视频生成节点；`校验报告` 和 `调试信息` 用于排查输入或请求问题。

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

### 透明素材生成链路（RH）
节点位于 **SynVow-prompt / 透明素材** 分类下，建议按下面顺序连接：

1. `SynVow 透明素材提示词生成器 (RH)`
   - 选择 `scene_preset`，填写 `custom_prompt`，输出 `prompts_list`。
   - `自动规划(LLM)` 会调用 RunningHub LLM；`规则预设(不调用LLM)` 不会调用 LLM。
   - 如需参考图拆层，将参考图接到 `product_or_reference_image`。
2. `RH GPT-Image-2 Alpha (T_batch)`
   - 接入 `prompts_list`，无图像输入时走文生图；有 `image1`~`image8` 时先上传参考图，再走 RunningHub image-to-image。
   - 只输出 `image_urls` 和 `status`，不输出 `IMAGE/MASK`，避免 Alpha 通道在 tensor 转换中丢失。
   - 透明素材建议默认使用 `gpt-image-2-低价通道`。实测 `gpt-image-2-官方` 可提交成功，但上游可能返回不带 alpha 的不透明 PNG，保存节点会提示“未检测到透明像素”。
3. `SynVow 透明PNG保存预览 (RH)`
   - 接入 `image_urls`，按 URL 下载原始图片并保存 RGBA PNG。
   - `save_path` 支持 ComfyUI output 相对路径，也支持 Windows 绝对路径。

### RH GPT-Image-2 产品六合一

节点位于 **SynVow-prompt / 产品图像** 分类，直接输出 ComfyUI `IMAGE`、最终英文提示词和状态信息。

1. 连接主图 `image`，选择产品精修、产品融入场景、模糊图片高清、移除物品、增加光效或扩图。
2. “产品融入场景”需连接 `reference_image`；“移除物品”和“增加光效”可连接加载图像节点的 `MASK`。
3. “扩图”会自动识别与画布边缘相连的纯白 `#ffffff` 区域并填充，不需要手动画 Mask。
4. `llm_model` 会读取 RunningHub 当前模型列表；选择具体模型时，LLM 会分析原图和选区并扩写最终提示词，选择“关闭”则直接使用本地模板。
5. 默认使用 RH GPT-Image-2 低价通道；官方通道支持 `quality`，低价通道会忽略该参数。
6. 本节点调用的是 RunningHub 标准模型 API，需要 **Enterprise-Shared（企业共享）API Key**；普通 Key 虽可上传图片，但提交模型任务时会返回错误码 `1014`。
7. 可选的 `llm_config` 在本节点中只用于提供 RunningHub 企业共享 API Key 作为备用来源。不要连接第三方 OpenAI-compatible Key，因为同一 Key 还会用于 RunningHub 图像上传与生成接口。

节点不会向 RH 图像接口发送透明背景字段，生成结果 URL 会自动下载并转换为普通 RGB `IMAGE`。

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

### SynVow H3 多参考提示词导演（RunningHub）

| 参数 | 类型 | 说明 |
|---|---|---|
| `模型` | COMBO | RunningHub LLM 模型下拉框 |
| `RunningHub LLM 域名` | COMBO | 自动优先 `.ai` 并回退 `.cn`，或固定其中一个域名 |
| `创作需求` | STRING | 中文创作目标和约束 |
| `任务模式` | COMBO | 自动判断、文生视频、首帧/尾帧/首尾帧图生、多图参考、多参考视频 |
| `内容类型` | COMBO | 含音乐 MV / 情绪短片、电商广告、数字人口播、动作等 |
| `图片_1` ~ `图片_9` | IMAGE（可选） | 会发送给视觉 LLM；每个插口只能接一张图片 |
| `视频_1` ~ `视频_3` | VIDEO（可选） | 不读取媒体内容，只使用编号和职责文本 |
| `音频_1` ~ `音频_3` | AUDIO（可选） | 不读取媒体内容，只使用编号和职责文本 |
| `图片/视频/音频职责说明` | STRING | 为每一路参考素材分配人物、产品、动作、节奏等职责 |
| `随机种子` | INT | 控制 ComfyUI 重新执行；固定输入和种子会复用缓存 |
| `llm_config` | SYNVOW_LLM_CONFIG（可选） | 第三方 OpenAI-compatible LLM 配置，连接后覆盖 RunningHub 域名和默认 Key |

**输出**：`H3 英文提示词`、`中文导演预览`、`提示词方案 JSON`、`媒体连接清单 JSON`、`校验报告`、`调试信息`

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
