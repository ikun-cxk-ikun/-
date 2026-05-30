import argparse
from pathlib import Path

from ppt_agent import generate_ppt
from ali_llm import generate_ppt_content


def main() -> None:
    parser = argparse.ArgumentParser(
        description="最简单的 PPT 生成 agent（可选接入阿里云大模型自动写内容）"
    )
    parser.add_argument("topic", help="PPT 的主题，例如：AI 简介")
    parser.add_argument(
        "-d",
        "--description",
        help="一句话描述需求（如：给小白介绍一下什么是 AI），如果提供则优先用阿里云大模型生成内容",
    )
    parser.add_argument(
        "-c",
        "--content",
        help="直接指定 PPT 的主要内容（长文本也可以），如果不填且没有 description，则使用简单示例内容",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="输出 PPT 路径（默认：<topic>.pptx）",
    )
    parser.add_argument(
        "--ali-api-key",
        type=str,
        default=None,
        help="可选：阿里云大模型 API Key；不填则从环境变量 ALIYUN_DASHSCOPE_API_KEY 读取",
    )

    args = parser.parse_args()

    topic: str = args.topic

    # 优先级：description + Ali 大模型 -> content 参数 -> 内置示例
    if args.description:
        print("正在调用阿里云大模型生成 PPT 内容，请稍候...")
        content = generate_ppt_content(
            topic=topic,
            description=args.description,
            api_key=args.ali_api_key,
        )
    else:
        content = args.content or (
            f"{topic} 的基本概念\n主要特点\n典型应用场景\n未来发展方向"
        )

    output_path: str = args.output or f"{topic}.pptx"

    ppt_path: Path = generate_ppt(topic, content, output_path)
    print(f"已生成 PPT：{ppt_path}")


if __name__ == "__main__":
    main()

