import openai
import requests
import queue
import threading
import json
import time
import logging
import os
import traceback
from datetime import datetime

from openai import OpenAI

# 配置日志系统
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("thought_processor.log", encoding='utf-8')
    ]
)
logger = logging.getLogger("ThoughtProcessor")


class APITransformer:
    def __init__(self, api_key, model="anthropic/claude-sonnet-4"):  # 可根据需要更改默认模型
        # 使用传入的API密钥，而不是硬编码
        self.api_key = api_key
        self.model = model  # 模型名称需符合OpenRouter的命名规范

        # 创建OpenRouter客户端连接
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1"
        )

        self.system_prompt = """
        你是一个技术面试思考生成器。请根据以下规则处理技术问题：
        1. 分析问题的核心考察点和技术领域
        2. 识别关键技术概念和评估标准
        3. 生成技术思考摘要（50字内）
        4. 预测可能的后续技术问题
        5. 如果是非技术问题，返回{"status": "reject", "reason": "非技术问题"}
        6. 输出必须是严格的JSON格式:{"keywords": [], "concepts": [], "summary": "", "prediction": "", "status": "process"}
        """
        logger.info(f"APITransformer 初始化完成 - 模型: {model}")

    def generate_thought(self, text_fragment, context="", is_partial=False):
        """调用大模型API生成技术思考（带流式响应）"""
        try:
            # 根据思考类型调整提示词
            if is_partial:
                full_prompt = f"当前输入片段: {text_fragment}\n请提取技术关键词和概念（不需要完整思考）"
                logger.debug(f"生成部分思考 - 文本: {text_fragment[:50]}...")
            else:
                full_prompt = f"上下文：{context}\n问题:{text_fragment}"
                logger.info(f"生成完整思考 - 文本: {text_fragment[:50]}... 上下文: {context[:50]}...")

            # 创建流式请求
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": full_prompt}
                ],
                max_tokens=200,
                temperature=0.3,
                top_p=0.7,
                stream=True,
                # 确保输出为JSON格式
                response_format={"type": "json_object"}
            )

            # 收集响应内容
            response_content = ""
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    response_content += content
                    # 如果是部分思考，实时更新
                    if is_partial:
                        logger.debug(f"API 流式响应: {content}")

            logger.debug(f"API 完整响应: {response_content}")

            # 尝试解析JSON响应
            try:
                # 尝试提取JSON内容
                if "{" in response_content and "}" in response_content:
                    start_index = response_content.index("{")
                    end_index = response_content.rindex("}") + 1
                    json_content = response_content[start_index:end_index]
                    result = json.loads(json_content)
                    logger.debug(f"成功解析JSON响应: {result}")
                else:
                    # 尝试直接解析整个内容
                    result = json.loads(response_content)
                    logger.debug(f"成功解析完整响应为JSON: {result}")
            except json.JSONDecodeError:
                logger.error(f"JSON解析错误: {response_content}")
                # 尝试手动提取关键信息
                result = self.extract_info_from_response(response_content)
                logger.warning(f"使用手动提取结果: {result}")

            # 如果是部分思考，只返回关键词和概念
            if is_partial:
                return {
                    'keywords': result.get('keywords', []),
                    'concepts': result.get('concepts', []),
                    'status': 'partial'
                }

            # 确保包含必要字段
            if 'status' not in result:
                result['status'] = 'process'

            return result

        except openai.AuthenticationError:
            logger.error("API密钥无效，请检查并更新密钥")
            return {
                "status": "error",
                "reason": "API密钥无效，请检查配置",
                "keywords": ["API错误"],
                "concepts": ["认证失败"],
                "summary": "API密钥无效，请检查配置"
            }

        except Exception as e:
            logger.error(f"API调用失败: {str(e)}")
            traceback.print_exc()
            return {
                "status": "error",
                "reason": f"API调用失败: {str(e)}"
            }

    def extract_info_from_response(self, content):
        """从非JSON响应中提取关键信息"""
        result = {
            "keywords": [],
            "concepts": [],
            "summary": "",
            "prediction": "",
            "status": "process"
        }

        # 尝试提取关键词
        if "keywords" in content:
            try:
                start = content.index("keywords") + len("keywords") + 3
                end = content.index("]", start)
                keywords_str = content[start:end]
                result["keywords"] = [kw.strip('" ') for kw in keywords_str.split(",")]
            except:
                pass

        # 尝试提取摘要
        if "summary" in content:
            try:
                start = content.index("summary") + len("summary") + 3
                end = content.index('"', start)
                result["summary"] = content[start:end]
            except:
                pass

        return result

class TechnicalFilter:
    """技术问题过滤器（优化版）"""

    def __init__(self):
        # 非技术话题关键词（包含个人问题）
        self.non_technical_keywords = [

            # 个人属性与隐私
            "个人", "家庭", "情感", "婚姻", "年龄", "性别", "宗教", "籍贯", "住址", 
            "电话", "邮箱", "身份证", "照片", "外貌", "身高", "体重", "健康", "疾病",
    
            # 生活琐事
            "天气", "时间", "日期", "假期", "周末", "节日", "礼物", "聚餐", "购物", 
            "电影", "音乐", "游戏", "宠物", "植物", "园艺", "旅行", "景点", "美食", 
            "厨艺", "减肥", "健身", "时尚", "穿搭", "美容", "护肤", "化妆", "发型",
    
            # 社会与争议话题
            "政治", "政党", "政策", "选举", "战争", "冲突", "宗教", "种族", "性别", 
            "堕胎", "同性恋", "移民", "难民", "疫情", "疫苗", "谣言", "八卦", "名人", 
            "网红", "直播", "短视频", "社交媒体", "舆论", "热搜", "绯闻", "丑闻",
    
            # 经济与消费
            "工资", "薪水", "奖金", "收入", "存款", "房贷", "车贷", "信用卡", "债务", 
            "投资", "股票", "基金", "加密货币", "比特币", "NFT", "房价", "物价", "通胀", 
            "失业", "裁员", "经济", " recession", "理财", "保险", "税收",
    
            # 其他非技术场景
            "兴趣", "爱好", "特长", "梦想", "理想", "未来规划", "职业规划", "跳槽", 
            "离职", "加班", "同事", "领导", "公司评价", "福利", "假期", "团建", "培训", 
            "考试", "成绩", "学校", "专业", "学历", "证书", "童年", "回忆", "超自然", 
            "外星人", "灵异", "风水", "算命", "星座", "占卜", "彩票", "赌博", "烟酒", 
            "毒品", "非法", "违规", "伦理", "道德"
]

        # 技术领域关键词
        self.technical_keywords = [

            # 基础编程与算法
            "算法", "数据结构", "编程", "代码", "语法", "编译", "解释", "调试", "测试", 
            "重构", "优化", "复杂度", "递归", "迭代", "排序", "搜索", "哈希", "树", 
            "图" , "栈", "队列", "链表", "数组", "字符串", "动态规划", "贪心", "回溯", 
            "分治", "缓存", "哈希表", "索引", "复杂度", "时间复杂度", "空间复杂度",
    
            #  编程语言与工具
            "Python", "Java", "C++", "JavaScript", "Go", "Rust", "PHP", "Ruby", "Swift", 
            "Kotlin", "TypeScript", "SQL", "NoSQL", "HTML", "CSS", "框架", "库", "SDK", 
            "API", "接口", "IDE", "编辑器", "Git", "SVN", "Docker", "Kubernetes", "CI/CD", 
            "Jenkins", "GitHub", "GitLab", "调试器", "性能分析", "单元测试", "集成测试",
    
            # 计算机系统与架构
            "操作系统", "Linux", "Windows", "macOS", "内核", "进程", "线程", "协程", 
            "内存", "缓存", "磁盘", "文件系统", "I/O", "中断", "调度", "同步", "异步", 
            "锁", "互斥", "并发", "并行", "分布式", "集群", "负载均衡", "高可用", 
            "容灾", "备份", "恢复", "虚拟化", "云原生", "微服务", "单体架构", "SOA", 
            "中间件", "消息队列", "RPC", "服务发现", "配置中心",
    
            # 网络与通信
            "网络", "协议", "TCP", "UDP", "HTTP", "HTTPS", "WebSocket", "TCP/IP", "DNS", 
            "CDN", "路由", "网关", "防火墙", "负载均衡", "代理", "反向代理", "Nginx", 
            "Apache", "SSL", "TLS", "加密", "解密", "认证", "授权", "OAuth", "JWT", 
            "RESTful", "GraphQL", "API网关", "网络安全", "DDoS", "入侵检测", "漏洞",
    
            # 数据库与存储
            "数据库", "MySQL", "PostgreSQL", "Oracle", "SQL Server", "MongoDB", "Redis", 
            "Cassandra", "Elasticsearch", "SQL", "NoSQL", "ORM", "事务", "ACID", "隔离级别", 
            "锁机制", "MVCC", "索引", "主键", "外键", "查询优化", "存储引擎", "分库分表", 
            "读写分离", "缓存", "持久化", "备份", "恢复", "数据一致性", "CAP理论",
    
            # 人工智能与机器学习
            "人工智能", "机器学习", "深度学习", "神经网络", "CNN", "RNN", "LSTM", "Transformer", 
            "GPT", "BERT", "模型", "训练", "推理", "预测", "分类", "回归", "聚类", "强化学习", 
            "监督学习", "无监督学习", "半监督学习", "特征工程", "特征提取", "归一化", "标准化", 
            "过拟合", "欠拟合", "正则化", "梯度下降", "反向传播", "激活函数", "卷积", "池化", 
            "注意力机制", "自注意力", "多头注意力", "位置编码", "预训练", "微调", "部署",
    
            # 云计算与大数据
            "云计算", "云服务", "IaaS", "PaaS", "SaaS", "FaaS", "AWS", "Azure", "GCP", "阿里云", 
            "腾讯云", "华为云", "服务器less", "大数据", "Hadoop", "Spark", "Flink", "MapReduce", 
            "流处理", "批处理", "数据湖", "数据仓库", "ETL", "数据清洗", "数据分析", "数据挖掘", 
            "可视化", "BI", "报表", "实时计算", "离线计算",
    
            # 安全与运维
            "安全", "加密", "解密", "哈希", "MD5", "SHA", "RSA", "AES", "密钥", "证书", 
            "漏洞", "渗透测试", "白帽", "黑帽", "XSS", "CSRF", "SQL注入", "权限", "认证", 
            "授权", "审计", "日志", "监控", "告警", "性能监控", "链路追踪", "APM", "运维", 
            "DevOps", "SRE", "自动化", "脚本", "部署", "发布", "回滚", "版本控制", "环境隔离"
]

        logger.info("技术过滤器初始化完成")

    def is_technical_question(self, text):
        """检查问题是否与技术相关"""
        text_lower = text.lower()

        # 1. 检查是否包含非技术关键词
        for keyword in self.non_technical_keywords:
            if keyword in text_lower:
                logger.info(f"检测到非技术关键词: {keyword} - 拒绝处理")
                return False

        # 2. 检查是否包含技术关键词
        for keyword in self.technical_keywords:
            if keyword in text_lower:
                logger.info(f"检测到技术关键词: {keyword} - 接受处理")
                return True

        # 3. 检查是否包含问题词
        question_words = ["如何", "怎样", "什么", "为什么", "哪些", "是否", "吗", "呢"]
        for word in question_words:
            if word in text_lower:
                logger.info(f"检测到问题词: {word} - 可能的技术问题")
                return True

        # 4. 默认拒绝
        logger.info("未检测到明显技术或问题特征 - 拒绝处理")
        return False


class TechnicalThoughtProcessor:
    def __init__(self, api_transformer):
        self.buffer = ""  # 文本缓冲区
        self.thought_state = {
            "keywords": set(),
            "concepts": [],
            "summary": "",
            "predictions": [],
            "status": "waiting",  # waiting, processing, rejected
            "current_input": ""  # 当前输入文本
        }
        self.api_transformer = api_transformer
        self.filter = TechnicalFilter()
        self.context_window = []  # 上下文窗口（存储思考摘要）
        self.context_limit = 5  # 最近的5个思考作为上下文
        self.context_expiry = 300  # 上下文有效期（秒）
        self.task_queue = queue.Queue()
        self.worker = threading.Thread(target=self._process_queue, daemon=True)
        self.worker.start()
        self.last_call_time = 0
        self.min_call_interval = 1.5  # 最小API调用间隔
        self.question_history = []  # 记录问题历史
        self.processed_count = 0  # 处理计数
        self.last_processed = time.time()  # 最后处理时间
        self.last_full_thought = None  # 最后一次完整思考

        # 实时思路展示相关
        self.realtime_updates = []
        self.update_lock = threading.Lock()
        self.last_partial_update = 0
        self.partial_interval = 0.8  # 部分思考更新间隔
        self.last_display_update = 0

        logger.info("技术思考处理器初始化完成")
        logger.info(f"API Transformer: {self.api_transformer.model}")

    def _clean_expired_context(self):
        """清理过期的上下文"""
        if not self.context_window:
            return

        current_time = time.time()
        # 过滤掉过期的上下文
        prev_count = len(self.context_window)
        self.context_window = [ctx for ctx in self.context_window
                               if current_time - ctx['timestamp'] < self.context_expiry]

        if prev_count > len(self.context_window):
            logger.info(f"清理了 {prev_count - len(self.context_window)} 条过期上下文")

    def _get_context(self):
        """获取最近的上下文摘要"""
        self._clean_expired_context()
        contexts = [ctx['summary'] for ctx in self.context_window]
        return " | ".join(contexts)

    def update(self, text_fragment):
        """处理新的ASR片段 - 实现边听边想"""
        try:
            # 更新当前输入
            self.buffer += text_fragment
            self.thought_state["current_input"] = self.buffer
            self.thought_state["timestamp"] = datetime.now().strftime("%H:%M:%S")

            logger.debug(f"更新缓冲区: {text_fragment} | 当前缓冲区: {self.buffer[:50]}...")

            # 1. 实时关键词提取（不调用API）
            new_keywords = self._extract_keywords(text_fragment)
            if new_keywords:
                self.thought_state['keywords'].update(new_keywords)
                with self.update_lock:
                    update_msg = f"检测到关键词: {', '.join(new_keywords)}"
                    self.realtime_updates.append(update_msg)
                logger.debug(f"提取到关键词: {new_keywords}")

            # 2. 部分思考生成（每0.8秒触发）
            current_time = time.time()
            if current_time - self.last_partial_update > self.partial_interval:
                self.last_partial_update = current_time
                if self.buffer.strip():
                    # 创建部分思考任务
                    self.task_queue.put((self.buffer, self._get_context(), True))
                    logger.debug(f"创建部分思考任务: {self.buffer[:30]}...")

            # 3. 完整句子处理（检测句子结束）
            sentence_end = any(punct in text_fragment for punct in ['.', '?', '!', '？', '。', ';'])
            if sentence_end:
                logger.info(f"检测到句子结束: {self.buffer[:50]}...")
                # 清理过期上下文
                self._clean_expired_context()

                # 快速过滤明显非技术问题
                if not self.filter.is_technical_question(self.buffer):
                    # 记录非技术问题
                    self.question_history.append({
                        "question": self.buffer,
                        "status": "non_technical",
                        "timestamp": datetime.now().isoformat()
                    })
                    logger.info(f"非技术问题已记录: {self.buffer[:30]}...")
                    self.buffer = ""
                    return self._current_thought()

                # 创建完整思考任务
                context = self._get_context()
                self.task_queue.put((self.buffer, context, False))
                logger.info(f"创建完整思考任务: {self.buffer[:30]}... | 上下文: {context[:50]}...")

                # 保存当前状态用于显示
                self.last_full_thought = self._current_thought()
                self.buffer = ""
                self.thought_state["current_input"] = ""

            # 返回当前思考状态
            thought = self._current_thought()
            logger.debug(f"返回当前思考状态: {thought.get('status')}")
            return thought
        except Exception as e:
            logger.error(f"更新处理器时出错: {str(e)}")
            traceback.print_exc()
            return {
                "status": "error",
                "reason": f"处理器错误: {str(e)}"
            }

    def _extract_keywords(self, text):
        """实时关键词提取（不使用API）"""
        # 提取技术关键词
        found = []
        for term in self.filter.technical_keywords:
            if term in text:
                found.append(term)
        return found

    def _process_queue(self):
        """后台处理API请求的线程 - 支持部分和完整思考"""
        logger.info("处理器后台线程启动")
        while True:
            try:
                text, context, is_partial = self.task_queue.get()
                logger.debug(f"处理队列任务: {text[:30]}... | 部分: {is_partial}")

                # 确保API调用间隔
                current_time = time.time()
                elapsed = current_time - self.last_call_time
                if elapsed < self.min_call_interval:
                    wait_time = self.min_call_interval - elapsed
                    logger.debug(f"等待 {wait_time:.2f} 秒以满足API调用间隔")
                    time.sleep(wait_time)

                # 调用API
                logger.info(f"调用API生成思考 - 文本: {text[:30]}... | 部分: {is_partial}")
                result = self.api_transformer.generate_thought(text, context, is_partial)
                self.last_call_time = time.time()
                self.processed_count += 1
                self.last_processed = time.time()

                # 处理结果
                if result:
                    # 部分思考处理
                    if is_partial:
                        self._process_partial_result(result, text)
                    # 完整思考处理
                    else:
                        self._process_full_result(result, text)
                else:
                    logger.warning("API返回空结果")
            except Exception as e:
                logger.error(f"后台线程错误: {str(e)}")
                traceback.print_exc()
            finally:
                self.task_queue.task_done()

    def _process_partial_result(self, result, text):
        """处理部分思考结果（不保存到历史）"""
        try:
            with self.update_lock:
                # 添加关键词更新
                if result.get('keywords'):
                    keywords = result['keywords']
                    self.thought_state['keywords'].update(keywords)
                    self.realtime_updates.append(f"识别主题: {', '.join(keywords)}")
                    logger.debug(f"部分思考添加关键词: {keywords}")

                # 添加概念更新
                if result.get('concepts'):
                    concepts = result['concepts']
                    self.thought_state['concepts'].extend(concepts)
                    for concept in concepts:
                        self.realtime_updates.append(f"识别概念: {concept}")
                    logger.debug(f"部分思考添加概念: {concepts}")
        except Exception as e:
            logger.error(f"处理部分结果时出错: {str(e)}")
            traceback.print_exc()

    def _process_full_result(self, result, text):
        """处理完整思考结果"""
        try:
            # 清空实时更新
            with self.update_lock:
                self.realtime_updates = []

            # 更新思考状态
            if result.get("status") == "reject":
                self.question_history.append({
                    "question": text,
                    "status": "rejected",
                    "timestamp": datetime.now().isoformat(),
                    "reason": result.get("reason", "非技术问题")
                })
                logger.info(f"问题被拒绝: {text[:30]}... | 原因: {result.get('reason', '')}")
            else:
                self._update_thought(result, text)
                self.question_history.append({
                    "question": text,
                    "status": "processed",
                    "timestamp": datetime.now().isoformat(),
                    "summary": result.get("summary", "")
                })
                logger.info(f"问题已处理: {text[:30]}... | 摘要: {result.get('summary', '')[:30]}...")

                if "summary" in result:
                    self.context_window.append({
                        "summary": result['summary'],
                        "timestamp": time.time()
                    })
                    if len(self.context_window) > self.context_limit:
                        self.context_window.pop(0)
                    logger.debug(f"添加上下文摘要: {result['summary'][:30]}...")
        except Exception as e:
            logger.error(f"处理完整结果时出错: {str(e)}")
            traceback.print_exc()

    def _update_thought(self, result, question_text):
        """整合API返回的思考结果"""
        # 更新关键词（去重）
        if "keywords" in result:
            new_keywords = set(result.get('keywords', []))
            self.thought_state['keywords'].update(new_keywords)
            logger.debug(f"添加关键词: {new_keywords}")

        # 更新概念列表（保留最新的）
        if "concepts" in result:
            new_concepts = [c for c in result.get('concepts', [])
                            if c not in self.thought_state['concepts']]
            self.thought_state['concepts'] = new_concepts + self.thought_state['concepts']
            logger.debug(f"添加概念: {new_concepts}")

        # 更新摘要
        if "summary" in result:
            self.thought_state['summary'] = result.get('summary', self.thought_state['summary'])
            logger.debug(f"更新摘要: {result['summary'][:20]}...")

        # 更新预测
        if "prediction" in result:
            self.thought_state['predictions'] = [result['prediction']]
            logger.debug(f"添加预测: {result['prediction'][:20]}...")

        # 更新状态
        self.thought_state["status"] = "processing"
        self.last_full_thought = self._current_thought()

    def _current_thought(self):
        """获取当前思考状态的快照"""
        # 添加默认摘要值
        summary = self.thought_state['summary'] if self.thought_state['summary'] else "正在分析中..."

        # 获取当前时间
        current_time = datetime.now()
        timestamp = current_time.strftime("%H:%M:%S")

        return {
            "timestamp": timestamp,
            "keywords": list(self.thought_state['keywords'])[-10:],  # 最多显示10个关键词
            "concepts": self.thought_state['concepts'][-5:],  # 最多显示5个概念
            "summary": summary,
            "prediction": self.thought_state['predictions'][-1] if self.thought_state['predictions'] else "",
            "status": self.thought_state["status"],
            "current_input": self.thought_state["current_input"],
            "realtime_updates": self.realtime_updates[-3:],  # 最多显示3条实时更新
            "processed_count": self.processed_count,
            "last_processed": time.strftime("%H:%M:%S", time.localtime(self.last_processed))
        }

    def get_real_time_thoughts(self):
        """获取实时思考状态，用于显示"""
        # 获取当前思考状态的快照
        thought = self._current_thought()

        # 添加额外的状态信息
        thought["context_size"] = len(self.context_window)
        thought["queue_size"] = self.task_queue.qsize()

        return thought

    def get_processor_status(self):
        """获取处理器状态信息"""
        return {
            "status": "active",
            "processed_count": self.processed_count,
            "last_processed": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_processed)),
            "queue_size": self.task_queue.qsize(),
            "api_calls": self.processed_count,
            "context_items": len(self.context_window),
            "memory_usage": f"{len(json.dumps(self.__dict__)) / 1024:.1f} KB"
        }