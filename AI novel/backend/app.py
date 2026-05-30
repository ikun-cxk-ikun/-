from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from rag import NovelQASystem
import logging
import os

app = Flask(__name__, 
            template_folder=os.path.join(os.path.dirname(__file__), "../frontend/templates"),
            static_folder=os.path.join(os.path.dirname(__file__), "../frontend/static"))
CORS(app)

# 初始化问答系统
logging.info("正在初始化问答系统...")
qa_system = NovelQASystem(
    novel_path=os.path.join(os.path.dirname(__file__), "../honglou.txt"),
    api_key="sk-e08b7bc87ed345d7bc34f1f6c3af1fb3" # 改成自己 的 API key
)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
def ask_question():
    data = request.json
    question = data.get('question', '')
    try:
        result = qa_system.ask_question(question)
        return jsonify({
            "answer": result.get("answer", ""),
            "sources": [doc.page_content[:200]+"..." for doc in result.get("source_documents", [])]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)