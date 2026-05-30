from flask import Flask, render_template, request, jsonify, session
from processor_module.thought_processor import APITransformer, TechnicalThoughtProcessor
import json
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'  # 请在生产环境中更改

# 全局变量存储处理器实例
thought_processor = None
api_transformer = None

# 固定的API配置
API_KEY = "sk-05b1e4b662b44e0aa6666e970b5f51f4"
MODEL = "qwen-flash"

@app.route('/')
def index():
    """主页 - 实时思考展示界面"""
    return render_template('index.html')

@app.route('/config')
def config():
    """配置页面 - API密钥和模型设置"""
    return render_template('config.html')

@app.route('/history')
def history():
    """历史记录页面"""
    return render_template('history.html')

@app.route('/api/init_processor', methods=['POST'])
def init_processor():
    """初始化思考处理器"""
    global thought_processor, api_transformer
    
    try:
        # 直接使用固定的API密钥和模型
        api_transformer = APITransformer(API_KEY, MODEL)
        thought_processor = TechnicalThoughtProcessor(api_transformer)
        
        # 保存配置到session
        session['api_key'] = API_KEY
        session['model'] = MODEL
        
        return jsonify({'success': True, 'message': '处理器初始化成功'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/process_text', methods=['POST'])
def process_text():
    """处理输入文本"""
    global thought_processor
    
    if not thought_processor:
        return jsonify({'success': False, 'error': '请先初始化处理器'})
    
    try:
        data = request.get_json()
        text = data.get('text', '')
        
        if not text.strip():
            return jsonify({'success': False, 'error': '请输入有效文本'})
        
        # 更新思考处理器
        result = thought_processor.update(text)
        
        return jsonify({'success': True, 'thought': result})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/get_realtime_thoughts')
def get_realtime_thoughts():
    """获取实时思考状态"""
    global thought_processor
    
    if not thought_processor:
        return jsonify({'success': False, 'error': '处理器未初始化'})
    
    try:
        thoughts = thought_processor.get_real_time_thoughts()
        return jsonify({'success': True, 'thoughts': thoughts})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/get_processor_status')
def get_processor_status():
    """获取处理器状态"""
    global thought_processor
    
    if not thought_processor:
        return jsonify({'success': False, 'status': 'not_initialized'})
    
    try:
        status = thought_processor.get_processor_status()
        return jsonify({'success': True, 'status': status})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/get_history')
def get_history():
    """获取处理历史"""
    global thought_processor
    
    if not thought_processor:
        return jsonify({'success': False, 'error': '处理器未初始化'})
    
    try:
        history = thought_processor.question_history[-50:]  # 最近50条记录
        return jsonify({'success': True, 'history': history})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/start_deep_thinking', methods=['POST'])
def start_deep_thinking():
    """启动深度思考"""
    global thought_processor
    
    if not thought_processor:
        return jsonify({'success': False, 'error': '请先初始化处理器'})
    
    try:
        data = request.get_json()
        question = data.get('question', '')
        
        if not question.strip():
            return jsonify({'success': False, 'error': '请输入有效问题'})
        
        result = thought_processor.start_deep_thinking(question)
        
        if result:
            return jsonify({'success': True, 'message': '深度思考已启动'})
        else:
            return jsonify({'success': False, 'error': '深度思考启动失败'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/get_deep_answer_stream')
def get_deep_answer_stream():
    """获取深度回答流"""
    global thought_processor
    
    if not thought_processor:
        return jsonify({'success': False, 'error': '处理器未初始化'})
    
    try:
        stream_data = thought_processor.get_deep_answer_stream()
        return jsonify({'success': True, 'stream': stream_data})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/stop_deep_thinking', methods=['POST'])
def stop_deep_thinking():
    """停止深度思考"""
    global thought_processor
    
    if not thought_processor:
        return jsonify({'success': False, 'error': '处理器未初始化'})
    
    try:
        result = thought_processor.stop_deep_thinking()
        
        if result:
            return jsonify({'success': True, 'message': '深度思考已停止'})
        else:
            return jsonify({'success': False, 'error': '停止失败'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/reset_processor', methods=['POST'])
def reset_processor():
    """重置处理器"""
    global thought_processor, api_transformer
    
    try:
        if thought_processor:
            # 停止深度思考
            thought_processor.stop_deep_thinking()
            
            # 清空状态
            thought_processor.buffer = ""
            thought_processor.thought_state = {
                "keywords": set(),
                "concepts": [],
                "summary": "",
                "predictions": [],
                "status": "waiting",
                "current_input": ""
            }
            thought_processor.question_history = []
            thought_processor.context_window = []
            thought_processor.deep_answer_content = ""
            thought_processor.deep_thinking_status = "待机中"
            
        return jsonify({'success': True, 'message': '处理器已重置'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    # 应用启动时自动初始化处理器
    try:
        api_transformer = APITransformer(API_KEY, MODEL)
        thought_processor = TechnicalThoughtProcessor(api_transformer)
        print(f"✅ 处理器已自动初始化 - 模型: {MODEL}")
    except Exception as e:
        print(f"⚠️ 处理器初始化失败: {e}")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
