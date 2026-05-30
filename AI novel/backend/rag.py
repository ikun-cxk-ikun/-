from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_community.embeddings.huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_classic.chains import RetrievalQA
from langchain_core.language_models import LLM
from typing import Any, List, Optional, Dict
from pydantic import Field, BaseModel
from openai import OpenAI
from tqdm import tqdm
import logging
import os

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class QwenLLM(LLM, BaseModel):
    api_key: str = Field(..., description="Qwen API key")
    
    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        try:
            # 初始化 OpenAI 客户端
            client = OpenAI(
                api_key=self.api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            
            # 发送请求
            logging.info("发送请求到 Qwen API...")
            completion = client.chat.completions.create(
                model="qwen-max",
                messages=[
                    {"role": "system", "content": "你是一个专业的文学评论家，请基于给定的文本回答问题。"},
                    {"role": "user", "content": prompt}
                ]
            )
            
            # 获取回答
            return completion.choices[0].message.content
                
        except Exception as e:
            logging.error(f"API 调用失败: {str(e)}")
            raise Exception(f"API 调用失败: {str(e)}")

    @property
    def _llm_type(self) -> str:
        return "qwen"
        
    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {"model": "qwen2.5-vl-72b-instruct"}

class NovelQASystem:
    def __init__(self, novel_path, api_key):
        self.novel_path = novel_path
        self.api_key = api_key
        
        # 检查是否存在缓存的向量存储
        self.vector_store_path = "vector_store"
        
        # 初始化各个组件
        self.embeddings = None
        self.vector_store = None
        self.qa_chain = None
        
        # 加载并初始化系统
        self._init_system()
    
    def _init_system(self):
        """初始化整个问答系统"""
        try:
            # 1. 加载文档
            logging.info("正在加载文档...")
            documents = self._load_documents()
            
            # 2. 文档分块
            logging.info("正在进行文档分块...")
            texts = self._split_documents(documents)
            
            # 3. 初始化embedding模型
            logging.info("正在初始化embedding模型...")
            self.embeddings = HuggingFaceEmbeddings(
                model_name="BAAI/bge-large-zh",
                model_kwargs={'device': 'cpu'},
                cache_folder="./models"
            )
            
            # 4. 创建或加载向量存储
            if os.path.exists(self.vector_store_path):
                logging.info("找到缓存的向量存储，正在加载...")
                self.vector_store = FAISS.load_local(
                    self.vector_store_path,
                    self.embeddings,
                    allow_dangerous_deserialization=True
                )
            else:
                logging.info("正在创建向量存储...")
                self.vector_store = FAISS.from_documents(texts, self.embeddings)
                
                # 保存向量存储到本地
                logging.info("保存向量存储到本地...")
                self.vector_store.save_local(self.vector_store_path)
            
            # 5. 初始化问答链
            logging.info("正在初始化问答链...")
            self._init_qa_chain()
            
            logging.info("系统初始化完成!")
            
        except Exception as e:
            logging.error(f"系统初始化失败: {str(e)}")
            raise
        
    def _load_documents(self):
        """加载文档"""
        try:
            loader = TextLoader(self.novel_path, encoding='utf-8')
            return loader.load()
        except Exception as e:
            logging.error(f"加载文档失败: {str(e)}")
            raise
    
    def _split_documents(self, documents):
        """文档分块"""
        text_splitter = CharacterTextSplitter(
            separator="\n",
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len
        )
        return text_splitter.split_documents(documents)
    
    def _init_qa_chain(self):
        """初始化问答链"""
        try:
            # 使用 Qwen LLM
            llm = QwenLLM(api_key=self.api_key)
            
            # 创建问答链
            self.qa_chain = RetrievalQA.from_chain_type(
                llm=llm,
                chain_type="stuff",
                retriever=self.vector_store.as_retriever(
                    search_kwargs={"k": 3}
                ),
                return_source_documents=True
            )
        except Exception as e:
            logging.error(f"初始化问答链失败: {str(e)}")
            raise
    
    def ask_question(self, question: str):
        """提问接口"""
        try:
            logging.info(f"处理问题: {question}")
            result = self.qa_chain.invoke({"query": question})
            return {
                "answer": result["result"],
                "source_documents": result["source_documents"]
            }
        except Exception as e:
            logging.error(f"回答问题时出错: {str(e)}")
            return {
                "error": f"回答问题时出错: {str(e)}"
            }
    
    def get_relevant_chunks(self, question: str, k=3):
        """获取相关文本片段"""
        try:
            return self.vector_store.similarity_search(question, k=k)
        except Exception as e:
            logging.error(f"获取相关文本片段失败: {str(e)}")
            return []

def main():
    try:
        # 使用示例
        novel_path = "AI novel\honglou.txt"  # 小说文件路径
        api_key = "sk-e08b7bc87ed345d7bc34f1f6c3af1fb3"  # 改成自己 的 API key
        
        # 初始化问答系统
        logging.info("正在初始化问答系统...")
        qa_system = NovelQASystem(novel_path, api_key)
        
        # 测试问题
        test_questions = [
            "贾宝玉是什么样的人物?",
            "林黛玉的性格特点是什么?",
            "小说中有哪些主要人物?",
            "林黛玉的结局"
        ]
        
        # 测试问答
        for question in test_questions:
            print(f"\n问题: {question}")
            result = qa_system.ask_question(question)
            
            if "error" in result:
                print(f"错误: {result['error']}")
            else:
                print(f"回答: {result['answer']}")
                print("\n相关文本片段:")
                for doc in result['source_documents'][:2]:
                    print(f"- {doc.page_content[:100]}...")
                    
    except Exception as e:
        logging.error(f"程序执行出错: {str(e)}")
        raise

if __name__ == "__main__":
    main()