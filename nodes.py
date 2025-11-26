import json
import urllib.request
import urllib.error
import ssl
import base64
import io
import torch
import numpy as np
from PIL import Image

class EcommercePromptGenerator:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "api_url": ("STRING", {
                    "multiline": False, 
                    "default": "https://api.openai.com/v1",
                }),
                "api_key": ("STRING", {
                    "multiline": False, 
                    "default": "", 
                    "placeholder": "sk-..."
                }),
                "model_name": ("STRING", {
                    "multiline": False, 
                    "default": "gemini-2.0-flash-exp",
                }),

                "product_type": ("STRING", {
                    "multiline": False,
                    "default": "美妆粉底液",
                }),
                "selling_points": ("STRING", {
                    "multiline": True,
                    "default": "持久显色、自动避障",
                }),
                "design_style": (
                    [
                        "简约 Ins 风",
                        "高级奢华",
                        "科技感",
                        "清新自然",
                        "国潮风",
                        "活泼撞色",
                        "极简工业风",
                        "梦幻唯美",
                    ],
                    {"default": "简约 Ins 风"}
                ),
                "seed": ("INT", {"default": 0, "min": 0, "max": 99999}),
            },
            "optional": {
                "product_image": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompts_list", "debug_info")
    OUTPUT_IS_LIST = (True, False)

    FUNCTION = "generate_prompts_with_vision"
    CATEGORY = "🛒 E-Commerce AI/Prompting"

    # --- 辅助函数：ComfyUI 图片 转 Base64 ---
    def tensor_to_base64(self, image):
        # ComfyUI 的图片是 Tensor (Batch, H, W, C)
        i = 255. * image[0].cpu().numpy()
        img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))

        # Resize if too large (max 1024x1024) to avoid 500 errors
        max_size = 1024
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=85) # 降低一点质量以减小体积
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{img_str}"

    def call_llm_vision(self, api_url, api_key, model, system_prompt, user_prompt, base64_image=None, seed=None):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "ComfyUI-NanoPrompt/1.0"
        }

        url = api_url.rstrip('/')
        if url.endswith('/chat'):
            url = f"{url}/completions"
        elif not url.endswith('/chat/completions'):
            url = f"{url}/chat/completions"

        # 构建 Vision Payload
        content_list = [{"type": "text", "text": user_prompt}]
        if base64_image:
            content_list.append({
                "type": "image_url",
                "image_url": {
                    "url": base64_image
                }
            })

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content_list}
        ]

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.7,
            "stream": False
        }
        
        if seed is not None:
            payload["seed"] = seed

        try:
            print(f"🔗 Calling API: {url}")
            print(f"🔑 Using model: {model}")
            
            # 使用未验证的 SSL 上下文，解决某些环境下找不到证书文件的问题 ([Errno 2] No such file or directory)
            ssl_context = ssl._create_unverified_context()
            
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req, timeout=120, context=ssl_context) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result['choices'][0]['message']['content']
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8')
            error_msg = f"HTTP Error {e.code}: {err_body}"
            print(f"❌ {error_msg}")
            return error_msg
        except urllib.error.URLError as e:
            # URLError 包含了文件路径错误
            error_msg = f"URL Error: {str(e)}\nAPI URL: {url}\nReason: {e.reason if hasattr(e, 'reason') else 'Unknown'}"
            print(f"❌ {error_msg}")
            return error_msg
        except Exception as e:
            error_msg = f"Error: {str(e)}\nAPI URL: {url}"
            print(f"❌ {error_msg}")
            return error_msg

    def generate_prompts_with_vision(self, api_url, api_key, model_name, product_type, selling_points, design_style, seed, product_image=None):
        
        base64_img = None
        if product_image is not None:
            base64_img = self.tensor_to_base64(product_image)

        # Unified System Prompt: Generate 10-screen detail page prompts as a JSON list
        system_instruction = """[角色] 你是一名资深电商详情页设计师与 AI 文生图提示词工程师，拥有丰富的电商视觉设计经验，精通详情页分屏逻辑、用户视觉动线设计、产品卖点可视化表达，擅长根据产品需求与客户诉求，拆分详情页第一屏、第二屏核心内容，并生成精准、可直接复制的文生图提示词，确保每屏风格统一且能突出产品核心价值。[技能] 分屏逻辑规划：根据产品类型与卖点，合理划分第一屏 (吸引注意力)、第二屏 (深化卖点) 的内容，符合用户浏览习惯；视觉与文案融合：精准匹配产品卖点设计主副文案，同时规划文案排版与画面构图的协调性，确保信息传递高效；提示词精准化：精通文生图提示词语法，能将分屏需求转化为包含 “主文案、副文案、排版、构图、画质” 的完整提示词，可直接复制使用；[总体规则] 严格按 “需求与产品接收 — 参考图分析 — 分屏提示词制作” 流程执行，不可擅自省略或跳过步骤。无论用户如何打断或修改意见，完成当前回答后，均引导进入流程下一步。严格按电商详情页分屏逻辑执行，每屏提示词内容必须包含 “主文案、副文案、设计与排版、画面主体与构图、画质与细节”5 个模块，不可遗漏；确保每屏的风格统一 (如色调、设计风格)，除主文案副文案内容用双引号标注，其他无需使用引号。无特殊字符，每屏提示词内容简洁，不冗长；
[语言规则] 严格识别用户输入的语言。如果用户输入的是中文，主副文案必须输出中文；如果用户输入的是英文，主副文案必须输出英文。
[防翻译指令] 如果生成的文案是中文，请在每条提示词的末尾追加一句英文强指令：“Ensure the text content remains in Chinese characters, do not translate to English.”
[功能][需求与产品接收]：让我们开启电商详情页分屏提示词创作～请您提供以下信息:Q1: 产品具体类型 (如美妆粉底液、家电 - 扫地机器人、服饰 - 牛仔外套)Q2: 产品核心卖点是什么？(如 “持久显色、自动避障” 等)同时，请告诉我您希望的设计风格？(如简约 ins 风、国潮风、科技感、清新自然风)您也可补充需求细节或参考图方向～待用户回答，收到产品需求、信息及风格后，执行 [参考图] 功能。[参考图分析]：竞品已分析完毕，接下来请您上传参考图，或者告诉我您想要的风格，我将结合需求与您的产品特色，策划专属详情页提示词。待用户回答，收到参考图及风格后，执行 [分屏提示词制作] 功能。[分屏提示词制作]：重要！根据客户需求文档内容写，不要修改各个客户每 — 屏的主标题副标题文案，每一屏风格保持统一。按以下模板生成第一屏、第二屏文生图提示词，确保每屏可直接复制，无多余内容:第一屏:主文案:“产品核心吸引点 (如 “20 小时长续航无线耳机”)”副文案：补充亮点 (如 “主动降噪，沉浸式听歌”)文案设计与排版：主文案居中放大，字体粗黑；副文案在主文案下方，字体纤细，颜色比主文案浅一度画面主体与构图：画面中心是产品 (无线耳机)，耳机摆投放置简约充电盒，背景为浅灰色渐变 + 细碎银色光点，右侧点缀 1-2 个耳机使用场景小插画 (如通勤佩戴); 整体构图对称画质与细节：高清 8K 分辨率，产品纹理清晰 (耳机金属边框反光可见)，色彩柔和，无模糊噪点，光影均匀[初始]：让我们开启电商详情页分屏提示词创作～请您提供:1. 产品具体类型 (如美妆粉底液、家电 - 空气炸锅)2. 产品核心卖点3. 希望的设计风格[角色] 你是一名资深电商详情页策划师，拥有丰富的各品类电商详情页设计经验，精通竞品详情页拆解、产品卖点提炼、文案适配及详情页架构规划，擅长结合竞品优势与产品特色，输出可直接落地的十屏左右详情页架构 (含主副标题、画面需求)。[技能]竞品分析：具体分析用户提供的竞品详情页，再结合用户上传的产品，拆解竞品详情页的视觉风格、文案逻辑、核心卖点，总结优劣势。文案策划：结合竞品短板与产品亮点，撰写贴合用户需求的详情页文案。架构规划：按电商转化逻辑，规划十屏左右详情页架构，主副标题≤10 字，以表格呈现画面需求。[总体规则] 严格按 “竞品分析 — 产品接收 — 文案策划 — 架构输出” 流程执行，不可擅自省略或跳过步骤。无论用户如何打断或修改意见，完成当前回答后，均引导进入流程下一步。画面需求不要有假设性等词语，需要具体的内容。[功能][竞品详情页拆解]：请您上传竞品图片，我将从视觉、文案、卖点三方面进行拆解分析，完成竞品图片后，输出详细的竞品分析报告，随后引导进入 [文案策划] 环节。[文案策划]：竞品已分析完成，请您上传您的产品 (可附产品图片、核心参数、特色卖点)，我将结合竞品优劣与您的产品特色，策划专属详情页文案。[详情页架构]：产品信息收到后，将输出针对性的详情页文案，随后引导进入 [详情页架构规划] 环节。[详情页架构规划]：按电商转化逻辑，规划 10 屏左右详情页，最后一屏是产品参数，每屏主标题≤10 字，画面需求需具体可落地，以表格形式呈现。2. 按以下模板输出详情页架构：[详情页架构表格模板]
屏幕序号	主标题 (≤10 字)	副标题 (≤10 字)	画面需求
1	主标题内容	副标题内容	具体画面描述，如 “产品全景图 + 品牌 LOGO，背景简洁”
2	主标题内容	副标题内容	具体画面描述，如 “产品核心卖点特写，配数据标注”
……	……	……	……
10	主标题内容	副标题内容	具体画面描述，如 “售后服务信息 + 购买按钮，色彩醒目”

[重要指令]
请忽略上述 prompt 中的交互步骤，直接基于用户提供的产品信息，一次性生成 10 屏的详情页提示词。
输出格式必须是 JSON 字符串列表 (List[str])，每个元素包含该屏的完整提示词（含主文案、副文案、画面描述等）。
不要输出 Markdown 表格，直接输出 JSON 列表。
**特别注意：文案语言必须与用户输入的语言保持一致（中文输入出中文文案，英文输入出英文文案）。**
**如果文案是中文，请在每条提示词末尾强制添加： "Ensure the text content remains in Chinese characters, do not translate to English."**
"""
            
        user_req = f"""
请为以下产品设计 10 屏详情页提示词：
1. 产品类型: {product_type}
2. 核心卖点: {selling_points}
3. 设计风格: {design_style}

(如果附带了图片，请将其作为产品外观参考)

请直接输出 JSON 列表。如果做不到，请确保每行一条提示词，共 10 行。
"""

        print(f"🎨 Gemini-3 Vision processing task: Generating 10-screen prompts...")
        response = self.call_llm_vision(api_url, api_key, model_name, system_instruction, user_req, base64_img, seed)

        # Parse the response into a list
        prompts_list = []
        try:
            # Clean up potential markdown code blocks
            cleaned_response = response.strip()
            if cleaned_response.startswith("```json"):
                cleaned_response = cleaned_response[7:]
            if cleaned_response.startswith("```"):
                cleaned_response = cleaned_response[3:]
            if cleaned_response.endswith("```"):
                cleaned_response = cleaned_response[:-3]
            
            prompts_list = json.loads(cleaned_response.strip())
            
            if not isinstance(prompts_list, list):
                # Fallback if not a list
                print("⚠️ Output is not a list, trying to split by newlines...")
                prompts_list = [line.strip() for line in response.split('\n') if line.strip()]
            
        except json.JSONDecodeError:
            print("⚠️ Failed to parse JSON response. Falling back to line splitting.")
            # Fallback: Split by newlines and filter empty lines
            prompts_list = [line.strip() for line in response.split('\n') if line.strip() and len(line.strip()) > 10]
            
            # If still only 1 item and it's very long, maybe it's a block of text?
            # But for now, line splitting is the best fallback.
            
        except Exception as e:
            print(f"❌ Error parsing response: {str(e)}")
            prompts_list = [response]

        # Ensure we have a list, even if it's single item
        if not prompts_list:
            prompts_list = ["Error: No prompts generated."]

        return (prompts_list, json.dumps({"input_summary": user_req, "raw_response": response}, ensure_ascii=False))

NODE_CLASS_MAPPINGS = {
    "EcommercePromptGenerator": EcommercePromptGenerator
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "EcommercePromptGenerator": "🛒 E-Commerce Prompt Generator (Gemini)"
}
