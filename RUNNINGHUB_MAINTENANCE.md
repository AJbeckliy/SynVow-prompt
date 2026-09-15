# RunningHub 维护交接

更新时间：2026-09-15

## 项目与分支

- 仓库：`https://github.com/AJbeckliy/SynVow-prompt`
- 已发布主分支提交：`630b020`
- 已合并PR：`https://github.com/AJbeckliy/SynVow-prompt/pull/4`
- 长期维护分支：`codex/runninghub-maintenance`
- 维护worktree：`I:\ComfyUI\dev_worktrees\SynVow-prompt-runninghub-maintenance`
- 用户正在使用的原目录：`I:\ComfyUI\custom_nodes\SynVow-prompt`

原目录在迁移前已有未提交修改：`__init__.py`、`prompt_nodes.py`。不要重置、覆盖或把它们误带入维护提交。

## 本次已完成

主分支已经合并以下RunningHub适配：

1. `SynVow 透明素材提示词生成器`
   - 固定2至6个图层槽位。
   - LLM规划完整画布比例、图层坐标和多个区域坐标。
   - 每层最终提示词控制在200至500字。
   - 参考图分层模式完全忽略风格参考图，输入原图是唯一视觉来源。

2. `SynVow 透明PNG保存预览`
   - 保存模型返回的RGBA PNG。
   - 背景层铺满并强制不透明。
   - 前景图层按LLM规划坐标恢复画布、大小和位置。
   - 不生成新蒙版，不把原图像素重新贴回图层。
   - 上游失败时保留槽位并生成黑图占位。

3. `SynVow PSD图层合成`
   - 将RGBA PNG按规划名称和顺序写入PSD。
   - 支持相对或绝对保存路径。
   - 可加入隐藏原图参考层并输出合成预览。
   - Python 3.10+安装`psd-tools>=1.19,<2`；旧Python环境仍可加载其它节点。

4. `RH GPT-Image-2 产品六合一`
   - 图像OpenAPI站点由`api_base_url`决定。
   - LLM自动跟随同站点，不再把国际模型发送到国内接口。
   - 只展示支持图片输入的LLM。
   - 保留原有API Key解析优先级。

## 明确不做

- 本次没有升级或修改`gpt_image_2_alpha_runninghub.py`。
- 新透明分层链路不推荐使用`RH GPT-Image-2 Alpha (T_batch)`。
- 图像生成直接连接RunningHub平台已有的GPT Image 2.5标准节点。
- 没有增加SAM、BiRefNet、自动检查、自动重试或二次蒙版分层。
- 没有实现可编辑文字PSD；该方向仍属于后续升级项目。

## RunningHub接口规则

参考项目：`https://github.com/HM-RunningHub/ComfyUI_RH_OpenAPI`

### 标准模型OpenAPI

- 国内站：`https://www.runninghub.cn/openapi/v2`
- 国际站：`https://www.runninghub.ai/openapi/v2`
- 图片上传：`{base_url}/media/upload/binary`
- 任务查询：`{base_url}/query`
- GPT Image 2.5标准节点由RunningHub平台提供，本插件不重复实现。

GPT Image 2.5透明PNG关键参数：

- `background=transparent`
- `outputFormat=png`
- 背景图层生成时改用`background=opaque`
- 图生图输入字段为`imageUrls`

### LLM网关

- 国内模型列表：`https://llm.runninghub.cn/v1/models`
- 国内聊天：`https://llm.runninghub.cn/v1/chat/completions`
- 国际模型列表：`https://llm.runninghub.ai/v1/models`
- 国际聊天：`https://llm.runninghub.ai/v1/chat/completions`

模型列表按站点独立缓存一小时。提示词生成器和六合一只展示`capabilities.vision=true`、`capabilities.multimodal=true`或输入模态包含`image`的模型。

## 2026-09-15实时模型快照

- 国内站：27个模型，其中14个支持图片。
- 国际站：74个模型，其中40个支持图片。
- 国际站比国内站多26个视觉模型。
- 国内视觉规划默认：`deepseek/deepseek-v4-flash-vision-exp`。
- 国际视觉规划默认：`google/gemini-3.5-flash`。
- `qwen/qwen3.7-max`在当日接口中明确为`vision=false`，不能作为参考图分层默认模型。

模型列表会变化。维护时必须重新请求两个`/v1/models`接口，不要把本快照当成永久事实。

## 验证证据

- 37项离线测试通过。
- Python语法检查通过。
- Ruff检查通过，保留ComfyUI运行日志输出。
- `web/runninghub_llm_site_models.js`语法检查通过。
- 提示词JSON解析通过。
- 节点注册验证通过。
- 密钥扫描无命中。
- 国内和国际模型接口实时读取通过。
- PR文件范围验证通过，Alpha批量节点零改动。

测试入口：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='I:\ComfyUI'
& 'I:\ComfyUI\python\python.exe' -m unittest discover -s tests
```

## 尚未验证

- RunningHub平台安装后的真实节点界面联动。
- 国内站和国际站分别使用有效企业共享Key完成一次LLM视觉规划。
- 平台现有GPT Image 2.5标准节点与`prompts_list`、参考图、结果URL的实际连接方式。
- 标准节点生成的透明PNG接入保存节点后的RGBA保留情况。
- PSD文件在RunningHub容器中的保存目录和下载方式。

以上项目必须由RunningHub平台技术环境验证。结构测试和本地模拟不能替代平台真实运行。

## 下一步维护顺序

1. 在RunningHub测试环境安装`codex/runninghub-maintenance`。
2. 检查提示词节点切换`.cn/.ai`后模型下拉是否实时变化。
3. 国内站使用国内视觉模型跑一次2层规划；国际站使用Gemini 3.5 Flash跑一次4层规划。
4. 将提示词连接到平台GPT Image 2.5标准节点，确认每层背景参数和结果URL。
5. 连接透明PNG保存节点，检查真实Alpha、画布比例和坐标。
6. 连接PSD合成节点，检查图层名称、顺序、隐藏参考层和保存路径。
7. 把平台错误日志、节点截图和输出文件保存到维护分支，再决定是否提交修复PR。

## 提交规则

- 维护改动只提交到`codex/runninghub-maintenance`或从它创建的短期功能分支。
- 不直接提交`main`。
- 不把原目录已有的`__init__.py`、`prompt_nodes.py`未提交修改带入维护分支。
- 每次改动必须包含对应测试和平台验证记录。
- 通过PR审核后才能合并主分支。
