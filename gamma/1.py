# For prerequisites running the following sample, visit 链接1
import os
import signal  # for keyboard events handling (press "Ctrl+C" to terminate recording)
import sys
import json  # 添加JSON支持
import importlib.util  # 动态导入模块
import threading  # 添加线程支持
import time

import dashscope
import pyaudio
from dashscope.audio.asr import *

mic = None
stream = None


# 动态导入2.py模块
def load_processor_module():
    module_name = "processor_module"
    file_path = "processor_module/2.py"

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None:
        raise ImportError(f"Could not load module from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# 尝试导入处理模块
try:
    processor_module = load_processor_module()
    # 创建思考处理器实例
    processor = processor_module.TechnicalThoughtProcessor(
        processor_module.APITransformer(
            api_key="sk-05b1e4b662b44e0aa6666e970b5f51f4",
            model="qwen-flash"
        )
    )
    print("成功加载2.py处理器模块")
except Exception as e:
    print(f"加载2.py处理器模块失败: {str(e)}")
    processor = None

# Set recording parameters
sample_rate = 16000  # sampling rate (Hz)
channels = 1  # mono channel
dtype = 'int16'  # data type
format_pcm = 'pcm'  # the format of the audio data
block_size = 3200  # number of frames per buffer


def init_dashscope_api_key():
    """
        Set your DashScope API-key. More information:
        链接2
    """

    if 'DASHSCOPE_API_KEY' in os.environ:
        dashscope.api_key = os.environ[
            'DASHSCOPE_API_KEY']  # load API-key from environment variable DASHSCOPE_API_KEY
    else:
        dashscope.api_key = 'sk-be62802f70a34d46b7b812530ef219b2'  # set API-key manually


# 共享文本缓冲区
shared_text_buffer = ""
buffer_lock = threading.Lock()


# 文本处理线程
def text_processing_thread():
    global shared_text_buffer
    while True:
        with buffer_lock:
            if shared_text_buffer:
                # 获取当前缓冲区内容并清空
                current_text = shared_text_buffer
                shared_text_buffer = ""

            # 如果没有文本，等待一段时间
            else:
                time.sleep(0.1)
                continue

        # 处理文本
        if processor:
            # 传递文本给处理器
            thought = processor.update(current_text)

            # 打印思考摘要
            if thought['status'] == 'processing' and thought['summary']:
                print(f"\n[技术思考] {thought['summary']}")
            elif thought['status'] == 'rejected':
                print(f"\n[非技术问题] {thought.get('reason', '')}")

        # 稍微休息一下防止CPU占用过高
        time.sleep(0.05)


# 启动文本处理线程
processing_thread = threading.Thread(target=text_processing_thread, daemon=True)
processing_thread.start()


# Real-time speech recognition callback
class Callback(RecognitionCallback):
    def __init__(self, *args,  ** kwargs):
        super().__init__(*args,  ** kwargs)
        self.last_sentence = ""  # 用于跟踪上一个句子状态
        self.current_buffer = ""  # 当前缓冲区

    def on_open(self) -> None:
        global mic
        global stream
        print('RecognitionCallback open.')
        mic = pyaudio.PyAudio()
        stream = mic.open(format=pyaudio.paInt16,
                          channels=1,
                          rate=16000,
                          input=True)

    def on_close(self) -> None:
        global mic
        global stream
        print('RecognitionCallback close.')
        stream.stop_stream()
        stream.close()
        mic.terminate()
        stream = None
        mic = None

    def on_complete(self) -> None:
        print('RecognitionCallback completed.')  # recognition completed

    def on_error(self, message) -> None:
        print('RecognitionCallback task_id: ', message.request_id)
        print('RecognitionCallback error: ', message.message)
        # Stop and close the audio stream if it is running
        if 'stream' in globals() and stream.active:
            stream.stop()
            stream.close()
        # Forcefully exit the program
        sys.exit(1)

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if 'text' in sentence:
            current_text = sentence['text']
            # 打印识别文本
            print(f'识别: {current_text}', end=' ', flush=True)

            # 将文本添加到共享缓冲区
            with buffer_lock:
                global shared_text_buffer
                shared_text_buffer += current_text

            if RecognitionResult.is_sentence_end(sentence):
                print()  # 换行
                # 添加句号表示句子结束
                with buffer_lock:
                    shared_text_buffer += "。 "
        else:
            print('RecognitionCallback: 收到无文本结果')


def signal_handler(sig, frame):
    print('Ctrl+C pressed, stop recognition ...')
    # Stop recognition
    recognition.stop()
    print('Recognition stopped.')
    print(
        '[Metric] requestId: {}, first package delay ms: {}, last package delay ms: {}'
        .format(
            recognition.get_last_request_id(),
            recognition.get_first_package_delay(),
            recognition.get_last_package_delay(),
        ))
    # Forcefully exit the program
    sys.exit(0)


# ... (前面的导入和初始化代码保持不变) ...
class RealTimeThoughtDisplay:
    def __init__(self):
        self.last_update = time.time()
        self.update_interval = 0.3  # 缩短更新间隔至300ms
        self.display_width = 80
        self.thought_history = []  # 存储历史思考记录
        self.max_history = 5  # 最多显示5条历史

    def display(self, thought):
        """在控制台中展示实时思考过程"""
        # 保存当前思考到历史
        if thought['status'] != 'waiting' and thought['summary']:
            self.thought_history.append(thought)
            if len(self.thought_history) > self.max_history:
                self.thought_history.pop(0)

        # 清空显示区域
        print("\033[F" * 20, end="")  # 向上移动20行确保清空整个区域
        print("\033[J", end="")

        # 显示标题
        print("=" * self.display_width)
        print("实时技术思考面板".center(self.display_width))
        print("=" * self.display_width)

        # 显示当前识别文本
        print(f"[当前输入] {thought['current_input']}\n")

        # 显示最新思考状态
        print(f"[{thought['timestamp']}] 状态: ", end="")
        if thought['status'] == 'processing':
            print("\033[92m技术分析中\033[0m")
        elif thought['status'] == 'rejected':
            print("\033[91m非技术问题\033[0m")
        else:
            print("\033[93m等待技术输入\033[0m")

        # 显示关键信息
        if thought['keywords']:
            print(f"\n\033[1m关键主题:\033[0m {', '.join(thought['keywords'])}")
        if thought['concepts']:
            print(f"\n\033[1m技术概念:\033[0m")
            for concept in thought['concepts']:
                print(f"  - {concept}")

        # 显示思考摘要
        if thought['summary']:
            print(f"\n\033[1m思考摘要:\033[0m {thought['summary']}")

        # 显示实时更新
        if thought['realtime_updates']:
            print("\n\033[1m实时分析:\033[0m")
            for update in thought['realtime_updates']:
                print(f"  - {update}")

        # 显示思考历史
        if self.thought_history:
            print("\n\033[1m思考历史:\033[0m")
            for i, hist in enumerate(self.thought_history[-3:], 1):  # 只显示最近3条
                print(f"{i}. [{hist['timestamp']}] {hist['summary']}")

        print("=" * self.display_width)
        print("语音识别中，按Ctrl+C退出".center(self.display_width))
        print("=" * self.display_width)

    def should_update(self):
        current_time = time.time()
        if current_time - self.last_update > self.update_interval:
            self.last_update = current_time
            return True
        return False


# 创建实时思路展示器
thought_display = RealTimeThoughtDisplay()


# 文本处理线程
def text_processing_thread():
    global shared_text_buffer
    while True:
        with buffer_lock:
            if shared_text_buffer:
                # 获取当前缓冲区内容并清空
                current_text = shared_text_buffer
                shared_text_buffer = ""

            # 如果没有文本，等待一段时间
            else:
                time.sleep(0.1)
                continue

        # 处理文本
        if processor:
            # 传递文本给处理器
            processor.update(current_text)

            # 更新实时思路展示
            if thought_display.should_update():
                thought = processor.get_real_time_thoughts()
                thought_display.display(thought)

        # 稍微休息一下防止CPU占用过高
        time.sleep(0.05)


# ... (后面的回调类和主函数保持不变) ...
# main function
if __name__ == '__main__':
    init_dashscope_api_key()
    print('Initializing ...')

    # Create the recognition callback
    callback = Callback()

    # Call recognition service by async mode, you can customize the recognition parameters, like model, format,
    # sample_rate For more information, please refer to 链接3
    recognition = Recognition(
        model='paraformer-realtime-v2',
        # 'paraformer-realtime-v1'、'paraformer-realtime-8k-v1'
        format=format_pcm,
        # 'pcm'、'wav'、'opus'、'speex'、'aac'、'amr', you can check the supported formats in the document
        sample_rate=sample_rate,
        # support 8000, 16000
        semantic_punctuation_enabled=False,
        callback=callback)

    # Start recognition
    recognition.start()

    signal.signal(signal.SIGINT, signal_handler)
    print("Press 'Ctrl+C' to stop recording and recognition...")
    print("开始语音识别，请说话...")

    # 主循环
    try:
        while True:
            if stream:
                data = stream.read(3200, exception_on_overflow=False)
                recognition.send_audio_frame(data)
            else:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("检测到中断，停止识别...")

    recognition.stop()