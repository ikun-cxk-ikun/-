"""
阿里云大模型（如通义千问）的一个最小封装，用于从一句话描述自动生成 PPT 文案。

注意：
- 出于安全考虑，这里不写死你的 API Key，而是从环境变量读取：
  ALIYUN_DASHSCOPE_API_KEY
- 你需要自己去阿里云控制台开通相关服务，并设置好这个环境变量。
"""

from __future__ import annotations

import os
from typing import Optional

import requests


DASHSCOPE_API_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
)


def _get_api_key(explicit_key: Optional[str] = None) -> str:
    key = explicit_key or os.getenv("ALIYUN_DASHSCOPE_API_KEY", "")
    if not key:
        raise RuntimeError(
            "未找到阿里云 API Key，请设置环境变量 ALIYUN_DASHSCOPE_API_KEY，"
            "或者在调用 generate_ppt_content 时传入 api_key 参数。"
        )
    return key


def generate_ppt_content(
    topic: str,
    description: str,
    api_key: Optional[str] = None,
    model: str = "qwen-turbo",
) -> str:
    """
    使用阿里云大模型，根据一句话描述生成适合做 PPT 的中文要点内容。

    返回的 content 是一段多行文本，每行/每句会被后续的 ppt_agent 自动拆成要点。
    """
    key = _get_api_key(api_key)

    prompt = f"""
你是一个 PPT 内容助手，现在要根据用户的一句话需求，输出适合直接放进 PPT 的中文要点。

要求：
- 围绕主题「{topic}」
- 用户的简要描述是：「{description}」
- 输出时尽量分成多行/多句，每行一句要点。
- 风格简洁清晰，适合作为 PPT 的项目符号。
- 不要输出 markdown，只输出纯文本。
"""

    payload = {
        "model": model,
        "input": {
            "prompt": prompt,
        },
        "parameters": {
            "temperature": 0.7,
        },
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(DASHSCOPE_API_URL, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    # 根据阿里云 dashscope 的典型返回结构做一个简单解析
    try:
        content = data["output"]["text"]
    except Exception:
        # 如果结构不一致，就直接整个 json 打平返回，方便调试
        content = str(data)

    return content.strip()

