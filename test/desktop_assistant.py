# -*- coding: utf-8 -*-
"""
浏览器智能助手 - 通过自然语言控制浏览器自动化
使用 browser-use + 阿里云API
支持多任务上下文连接，浏览器保持打开状态
支持语音输入（通义 qwen3-asr-flash-realtime 实时识别）与文字输入
"""

import os
import sys
import asyncio
import base64
import queue
import threading
import time
from typing import List, Tuple, Optional
from browser_use import (
    Agent as BrowserAgent,
    Browser as SharedBrowser,
    ChatOpenAI as BrowserChatOpenAI,
    Tools as BrowserTools,
    ActionResult as BrowserActionResult,
)

# 语音输入：通义实时 ASR（qwen3-asr-flash-realtime），与浏览器 LLM 共用 API Key
try:
    import dashscope
    from dashscope.audio.qwen_omni import (
        OmniRealtimeConversation,
        OmniRealtimeCallback,
        MultiModality,
    )
    from dashscope.audio.qwen_omni.omni_realtime import TranscriptionParams
    ASR_REALTIME_AVAILABLE = True
except ImportError:
    ASR_REALTIME_AVAILABLE = False
    dashscope = None

# 统一输入行：Windows 用 msvcrt；F8 同时用 pynput 备用（部分终端需此才能识别 F8）
PYNPUT_AVAILABLE = False
keyboard = None
try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    pass

# 全局共享的浏览器实例（一个长对话只启动一次浏览器）
_SHARED_BROWSER = None

# 全局对话历史，用于维护上下文联系
_CONVERSATION_HISTORY: List[Tuple[str, str]] = []  # [(用户任务, 执行结果), ...]

# ==================== 配置区 ====================
# browser-use 使用的阿里云 LLM
BROWSER_LLM_API_KEY = os.getenv("ALIBABA_CLOUD", "sk-05b1e4b662b44e0aa6666e970b5f51f4")
BROWSER_LLM_BASE_URL = os.getenv("ALIBABA_CLOUD_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
# 推荐用通义千问视觉模型，支持网页截图理解
BROWSER_LLM_MODEL = os.getenv("BROWSER_LLM_MODEL", "qwen3-omni-flash-2025-12-01")

# 实时语音识别：与上面共用 API Key，使用 qwen3-asr-flash-realtime（非文件上传）
ASR_REALTIME_MODEL = "qwen3-asr-flash-realtime"
ASR_REALTIME_URL = os.getenv(
    "ASR_REALTIME_URL",
    "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
)
# 录音参数：16kHz 单声道 16bit PCM，与 API 要求一致
SAMPLE_RATE = 16000
CHUNK_FRAMES = 3200  # 约 0.2 秒每块
MAX_RECORD_SECONDS = 30


# ==================== browser-use 浏览器智能代理 ====================
async def _run_browser_agent(task: str, include_context: bool = True) -> str:
    """
    使用 browser-use + 阿里云 LLM 在浏览器里自动完成复杂网页操作
    支持上下文连接，多个任务可以共享浏览器状态和对话历史
    """
    if not BROWSER_LLM_API_KEY:
        return "未配置阿里云 API Key，请在环境变量 ALIBABA_CLOUD 中设置，或修改代码中的 BROWSER_LLM_API_KEY。"

    llm = BrowserChatOpenAI(
        model=BROWSER_LLM_MODEL,
        api_key=BROWSER_LLM_API_KEY,
        base_url=BROWSER_LLM_BASE_URL,
    )

    # 复用一个全局浏览器实例，这样一个长对话里只会打开一次浏览器窗口
    # 使用 keep_alive=True 保持浏览器打开，不自动关闭
    global _SHARED_BROWSER
    if _SHARED_BROWSER is None:
        _SHARED_BROWSER = SharedBrowser(
            headless=False,                 # 显示真实浏览器窗口
            window_size={"width": 1200, "height": 800},
            keep_alive=True,                # 关键：保持浏览器打开，不自动关闭
        )
        # 启动浏览器（keep_alive=True 时必须先启动）
        await _SHARED_BROWSER.start()

    # 构建包含上下文的任务描述
    global _CONVERSATION_HISTORY
    task_description = task
    
    # 如果启用上下文且存在历史记录，将之前的对话历史添加到任务描述中
    if include_context and _CONVERSATION_HISTORY:
        context_info = "\n\n【之前的操作历史（供参考上下文）：】\n"
        for idx, (prev_task, prev_result) in enumerate(_CONVERSATION_HISTORY, 1):
            context_info += f"{idx}. 任务：{prev_task}\n   结果：{prev_result}\n"
        context_info += "\n【当前任务】\n"
        task_description = context_info + task + "\n\n注意：浏览器当前可能已经打开在某个页面，请基于当前浏览器状态继续操作。"
    
    # 构建完整的任务提示
    full_task = (
        f"{task_description}\n\n"
        "请严格遵守以下规则：\n"
        "1. 当你完成用户要求的最后一步（例如：目标页面已打开、搜索结果已展示、表单已提交等）时，"
        "   必须立即结束任务，不要再继续点击或刷新。\n"
        "2. 如果你已经重复尝试多次仍然无法继续推进，也要停止并给出失败原因，而不是一直重复同一操作。\n"
        "3. 在任务结束时，给出一句话总结你做了什么。\n"
        "4. 如果浏览器已经打开在某个页面，请基于当前页面状态继续操作，不要重复打开已经打开的页面。\n"
        "5. 当需要用户提供信息时（例如：登录需要手机号/验证码、注册需要账号/密码/邮箱、表单需要用户填写的内容等），"
        "   必须调用 ask_human 工具向用户提问，把要问的问题作为参数传入，拿到用户回答后再继续操作，不要猜测或留空。"
    )

    # 自定义工具：遇到需要用户提供的信息时向用户提问（人机协作）
    tools = BrowserTools()

    @tools.action(
        description=(
            "当需要用户提供信息时调用此工具。例如：登录时的账户名、手机号、验证码、密码；"
            "注册时的账号、密码、邮箱、手机号；表单中需要用户填写的任何内容。"
            "传入你要问用户的具体问题（如：请输入手机号、验证码是多少），用户会在终端输入或语音回答，"
            "然后把用户回答的内容用于后续操作。"
        )
    )
    async def ask_human(question: str) -> BrowserActionResult:
        """向用户提问并等待用户输入，用于登录、注册、验证码等需要用户提供信息的场景。"""
        # 在异步上下文中用 to_thread 执行阻塞的 input，避免卡住事件循环
        loop = asyncio.get_event_loop()
        prompt = f"\n[助手需要您提供] {question}\n您的回答 > "
        answer = await asyncio.to_thread(lambda: (input(prompt) or "").strip())
        return BrowserActionResult(extracted_content=f"用户回答：{answer}" if answer else "用户未输入内容")

    # 创建 Agent，复用同一个浏览器会话，并注入「向用户求助」工具
    # 使用 browser_session 参数而不是 browser 参数，以保持浏览器连接
    agent = BrowserAgent(
        task=full_task,
        llm=llm,
        browser_session=_SHARED_BROWSER,  # 关键：使用 browser_session 参数保持浏览器打开
        tools=tools,
        use_vision=True,  # 让模型能看网页截图，复杂页面更稳
        max_failures=3,   # 避免一直在错误步骤重试
    )

    # 限制整体步数，防止在最后一步来回折腾
    history = await agent.run(max_steps=30)
    steps = len(history or [])
    result = f"已通过浏览器智能代理执行任务: {task}（共执行 {steps} 步）"
    
    # 保存到对话历史
    _CONVERSATION_HISTORY.append((task, result))
    
    return result


# 全局事件循环，用于保持浏览器连接
_MAIN_LOOP = None

def browser_agent(task: str, include_context: bool = True) -> str:
    """
    同步封装，直接执行浏览器自动化任务
    include_context: 是否包含之前的对话历史作为上下文
    
    使用持久的事件循环来保持浏览器连接，避免每次创建新循环导致浏览器关闭
    """
    global _MAIN_LOOP
    
    # 使用持久的事件循环，避免每次创建新的循环导致浏览器关闭
    try:
        # 尝试获取当前事件循环
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Event loop is closed")
    except RuntimeError:
        # 如果没有事件循环或已关闭，创建新的并保存
        _MAIN_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_MAIN_LOOP)
        loop = _MAIN_LOOP
    
    # 在现有循环中运行任务（不关闭循环）
    if loop.is_running():
        # 如果循环正在运行，使用线程池来运行
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                lambda: asyncio.run(_run_browser_agent(task, include_context))
            )
            return future.result()
    else:
        # 如果循环没有运行，直接运行（但不关闭循环）
        return loop.run_until_complete(_run_browser_agent(task, include_context))


def clear_conversation_history():
    """清空对话历史，开始新的对话"""
    global _CONVERSATION_HISTORY
    _CONVERSATION_HISTORY = []
    return "对话历史已清空"


def get_conversation_history() -> List[Tuple[str, str]]:
    """获取当前的对话历史"""
    return _CONVERSATION_HISTORY.copy()


async def _close_browser_async():
    """异步关闭浏览器"""
    global _SHARED_BROWSER
    if _SHARED_BROWSER is not None:
        try:
            # browser-use 的 Browser 对象有 kill() 方法来关闭浏览器
            if hasattr(_SHARED_BROWSER, 'kill'):
                await _SHARED_BROWSER.kill()
            elif hasattr(_SHARED_BROWSER, 'close'):
                await _SHARED_BROWSER.close()
        except Exception as e:
            print(f"关闭浏览器时出错: {e}")
        _SHARED_BROWSER = None
        return "浏览器已关闭"
    return "浏览器未打开"


# ==================== 语音输入（通义实时 ASR ） ====================
def get_voice_input_realtime(
    language: str = "zh",
    stop_event: Optional[threading.Event] = None,
) -> Optional[str]:
    """
    使用通义 qwen3-asr-flash-realtime 实时语音识别（不传文件，麦克风流式）。
    与浏览器 LLM 共用 BROWSER_LLM_API_KEY。
    stop_event: 若提供，则由调用方设置该 Event 来结束录音（如长按 v 松手）；
                否则内部通过「按 Enter」结束。
    """
    if not ASR_REALTIME_AVAILABLE or not BROWSER_LLM_API_KEY:
        return None
    try:
        import pyaudio
    except ImportError:
        print("[提示] 实时语音需要 pyaudio: pip install pyaudio")
        return None

    transcripts: List[str] = []
    stop_flag = stop_event if stop_event is not None else threading.Event()

    class RealtimeASRCallback(OmniRealtimeCallback):
        def on_event(self, message):
            if not isinstance(message, dict):
                return
            if message.get("type") == "conversation.item.input_audio_transcription.completed":
                t = message.get("transcript") or message.get("text") or ""
                if t:
                    transcripts.append(t)

    api_key = BROWSER_LLM_API_KEY
    if dashscope is not None:
        dashscope.api_key = api_key
    callback = RealtimeASRCallback()
    conversation = OmniRealtimeConversation(
        model=ASR_REALTIME_MODEL,
        callback=callback,
        url=ASR_REALTIME_URL,
        api_key=api_key,
    )
    conversation.connect()
    conversation.update_session(
        output_modalities=[MultiModality.TEXT],
        enable_turn_detection=True,
        turn_detection_type="server_vad",
        turn_detection_threshold=0.0,
        turn_detection_silence_duration_ms=400,
        enable_input_audio_transcription=True,
        transcription_params=TranscriptionParams(
            language=language,
            sample_rate=SAMPLE_RATE,
            input_audio_format="pcm",
        ),
    )

    if stop_event is None:
        def wait_enter():
            input()
            stop_flag.set()
        print("\n🎤 正在监听（通义实时 ASR），请说话… 说完后按 Enter 结束")
        threading.Thread(target=wait_enter, daemon=True).start()

    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_FRAMES,
    )
    try:
        total_sent = 0
        while not stop_flag.is_set() and total_sent < SAMPLE_RATE * MAX_RECORD_SECONDS:
            try:
                data = stream.read(CHUNK_FRAMES, exception_on_overflow=False)
            except Exception:
                break
            b64 = base64.b64encode(data).decode("utf-8")
            conversation.append_audio(b64)
            total_sent += len(data)
        stream.stop_stream()
    finally:
        stream.close()
        p.terminate()

    try:
        conversation.end_session(timeout=20)
    except Exception:
        pass
    try:
        conversation.close()
    except Exception:
        pass

    result = "".join(transcripts).strip()
    if result:
        print(f"✅ 识别结果: {result}")
    return result if result else None


def get_voice_input(language: str = "zh") -> Optional[str]:
    """
    语音转文字：使用通义 qwen3-asr-flash-realtime 实时 ASR。
    language: 中文 "zh"，英文 "en"。
    """
    if not ASR_REALTIME_AVAILABLE or not BROWSER_LLM_API_KEY:
        print("[提示] 语音输入需要: pip install dashscope pyaudio，并配置 API Key")
        return None
    return get_voice_input_realtime(language=language if language in ("zh", "en") else "zh")


def _redraw_line(prompt: str, buffer: List[str], lock: threading.Lock) -> None:
    with lock:
        s = "".join(buffer)
    line = prompt + s
    sys.stdout.write("\r\033[K" + line)
    sys.stdout.flush()


# Windows: 用 msvcrt 逐键读取，不挂钩键盘，中文 IME 和 Ctrl+C 正常
def _read_line_with_voice_windows(prompt: str = "请输入浏览器任务 > ") -> Optional[str]:
    import msvcrt

    buffer: List[str] = []
    lock = threading.Lock()
    voice_result_queue: queue.Queue = queue.Queue()
    recording_active = [False]
    recording_thread = [None]
    stop_recording = threading.Event()
    f8_pressed_flag = [False]  # pynput 备用：收到 F8 时置 True

    # 获取控制台输入代码页，用于正确解码中文（避免出现菱形乱码）
    def _console_encoding() -> str:
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            cp = kernel32.GetConsoleCP()
            if cp == 65001:
                return "utf-8"
            if cp == 936:
                return "gbk"
            return "gbk" if cp in (936, 950, 932) else "utf-8"
        except Exception:
            return "gbk"

    # F8 在 Windows 下为 0x00 或 0xE0 后跟 0x77（必须紧接着读第二字节，不能依赖 kbhit）
    VK_F8 = 0x77

    def voice_result_handler() -> None:
        while True:
            try:
                item = voice_result_queue.get(timeout=0.3)
                if item is None:
                    return
                text = (item or "").strip()
                if not text:
                    continue
                with lock:
                    buffer.extend(list(text))
                _redraw_line(prompt, buffer, lock)
            except queue.Empty:
                continue

    def do_record() -> None:
        try:
            stop_recording.clear()
            if not ASR_REALTIME_AVAILABLE or not BROWSER_LLM_API_KEY:
                print("\r[错误] 语音识别不可用", end="", flush=True)
                voice_result_queue.put("")
                return
            result = get_voice_input_realtime(language="zh", stop_event=stop_recording)
            print(f"\r[识别完成] {result or '(无)'}", end="", flush=True)
            voice_result_queue.put(result or "")
        except Exception as e:
            print(f"\r[录音错误] {e}", end="", flush=True)
            voice_result_queue.put("")
        finally:
            recording_active[0] = False
            recording_thread[0] = None

    voice_handler = threading.Thread(target=voice_result_handler, daemon=True)
    voice_handler.start()

    # pynput 备用：仅监听 F8，部分终端下 msvcrt 收不到 F8 时仍可响应
    pynput_listener = None
    if PYNPUT_AVAILABLE and keyboard:

        def _on_press(k):
            try:
                if k == keyboard.Key.f8:
                    f8_pressed_flag[0] = True
            except Exception:
                pass

        pynput_listener = keyboard.Listener(on_press=_on_press)
        pynput_listener.daemon = True
        pynput_listener.start()

    def discard_f8_escape() -> None:
        """pynput 触发 F8 时，丢弃终端可能发送的 ESC [ 19~ 等字节，避免变成正文"""
        if not msvcrt.kbhit():
            return
        b1 = msvcrt.getch()
        if b1 != b"\x1b":
            return
        if not msvcrt.kbhit():
            return
        b2 = msvcrt.getch()
        if b2 != b"[":
            return
        for _ in range(6):
            if msvcrt.kbhit():
                msvcrt.getch()
            else:
                break

    sys.stdout.write(prompt)
    sys.stdout.flush()

    def get_key() -> Optional[str]:
        """读一个按键，返回 'enter'/'backspace'/'f8'/'ctrl_c' 或单个字符。"""
        if not msvcrt.kbhit():
            return None
        b1 = msvcrt.getch()
        if b1 in (b"\r", b"\n"):
            return "enter"
        if b1 == b"\x08":
            return "backspace"
        if b1 == b"\x03":
            return "ctrl_c"
        # 扩展键（传统 CMD）：首字节 0x00 或 0xE0 后跟 0x77
        if b1 in (b"\x00", b"\xe0"):
            b2 = msvcrt.getch()
            if len(b2) == 1 and ord(b2) == VK_F8:
                return "f8"
            return None
        # Cursor/VS Code 等终端：F8 为 ESC [ 19~ 或 ESC [ 19;...~
        if b1 == b"\x1b":
            if not msvcrt.kbhit():
                return "\x1b"
            b2 = msvcrt.getch()
            if b2 == b"[":
                # 阻塞读至多 8 字节直到遇到 ~，再判断是否含 19（F8）
                seq = b""
                for _ in range(8):
                    c = msvcrt.getch()
                    seq += c
                    if c == b"~":
                        break
                try:
                    if b"19" in seq and seq.endswith(b"~"):
                        return "f8"
                except Exception:
                    pass
            return None
        try:
            enc = _console_encoding()
            first = b1[0]
            # ASCII
            if first < 0x80:
                return b1.decode("utf-8", errors="replace")
            # 按控制台代码页正确读多字节
            if enc == "utf-8":
                need = 2 if 0xC2 <= first <= 0xDF else (3 if 0xE0 <= first <= 0xEF else (4 if 0xF0 <= first <= 0xF4 else 1))
                for _ in range(need - 1):
                    b1 += msvcrt.getch()
                return b1.decode("utf-8", errors="replace")
            # GBK/CP936：首字节 0x81–0xFE 再读一字节
            if first >= 0x81:
                b1 += msvcrt.getch()
            return b1.decode(enc, errors="replace")
        except Exception:
            return None

    try:
        while True:
            # 优先检查 pynput 收到的 F8（部分终端 msvcrt 收不到 F8）
            if f8_pressed_flag[0]:
                f8_pressed_flag[0] = False
                discard_f8_escape()
                key = "f8"
            else:
                key = get_key()
            if key is None:
                time.sleep(0.02)
                continue
            if key == "ctrl_c":
                voice_result_queue.put(None)
                raise KeyboardInterrupt
            if key == "enter":
                with lock:
                    line = "".join(buffer)
                voice_result_queue.put(None)
                return line.strip() or None
            if key == "backspace":
                with lock:
                    if buffer:
                        buffer.pop()
                _redraw_line(prompt, buffer, lock)
                continue
            if key == "f8":
                if recording_active[0]:
                    print("\r[F8] 停止录音...", end="", flush=True)
                    stop_recording.set()
                else:
                    if recording_thread[0] and recording_thread[0].is_alive():
                        stop_recording.set()
                        recording_thread[0].join(timeout=0.5)
                    print("\r[F8] 开始录音...", end="", flush=True)
                    recording_active[0] = True
                    t = threading.Thread(target=do_record, daemon=True)
                    recording_thread[0] = t
                    t.start()
                continue
            if len(key) == 1 or len(key) > 1:
                with lock:
                    buffer.append(key)
                _redraw_line(prompt, buffer, lock)
    finally:
        try:
            voice_result_queue.put(None)
        except Exception:
            pass
        if pynput_listener is not None:
            try:
                pynput_listener.stop()
            except Exception:
                pass


class _CtrlCSentinel:
    """用于在 pynput 分支中表示用户按了 Ctrl+C"""
    pass


def read_line_with_voice(prompt: str = "请输入浏览器任务 > ") -> Optional[str]:
    """
    统一输入行：直接打字即输入；按 F8 开始录音，再按 F8 停止并识别，结果自动追加到当前行，Enter 提交。
    Windows 下用 msvcrt 逐键读（不挂钩），中文 IME 和 Ctrl+C 正常；其他平台用 pynput。
    """
    if sys.platform == "win32":
        return _read_line_with_voice_windows(prompt)
    if not PYNPUT_AVAILABLE:
        return input(prompt).strip()

    buffer: List[str] = []
    lock = threading.Lock()
    result_queue: queue.Queue = queue.Queue()
    voice_result_queue: queue.Queue = queue.Queue()
    recording_active = [False]  # 是否正在录音
    recording_thread = [None]  # 录音线程引用
    stop_recording = threading.Event()

    def voice_result_handler() -> None:
        while True:
            try:
                item = voice_result_queue.get(timeout=0.3)
                if item is None:
                    return
                text, _ = item
                s = (text or "").strip()
                if not s:
                    continue
                with lock:
                    buffer.extend(list(s))
                _redraw_line(prompt, buffer, lock)
            except queue.Empty:
                continue

    def do_record() -> None:
        try:
            stop_recording.clear()
            if not ASR_REALTIME_AVAILABLE or not BROWSER_LLM_API_KEY:
                print("\r[错误] 语音识别不可用，请检查 dashscope 和 API Key", end="", flush=True)
                voice_result_queue.put(("", 0))
                recording_active[0] = False
                return
            result = get_voice_input_realtime(language="zh", stop_event=stop_recording)
            if result:
                print(f"\r[识别完成] {result}", end="", flush=True)
            else:
                print("\r[识别完成] 未识别到内容", end="", flush=True)
            voice_result_queue.put((result or "", 0))
        except Exception as e:
            print(f"\r[录音错误] {e}", end="", flush=True)
            voice_result_queue.put(("", 0))
        finally:
            recording_active[0] = False
            recording_thread[0] = None

    def on_press(key) -> None:
        try:
            # 调试：打印按键（可选，调试时启用）
            # print(f"[DEBUG] 按键按下: {key}", flush=True)
            
            if key == keyboard.Key.enter:
                with lock:
                    result_queue.put("".join(buffer))
                return False  # 停止监听

            # Ctrl+C：放入哨兵，主线程会抛出 KeyboardInterrupt
            if hasattr(key, "char") and key.char == "\x03":
                result_queue.put(_CtrlCSentinel())
                return False

            if key == keyboard.Key.backspace:
                with lock:
                    if buffer:
                        buffer.pop()
                _redraw_line(prompt, buffer, lock)
                return

            if key == keyboard.Key.f8:
                if recording_active[0]:
                    # 正在录音，停止录音
                    print("\r[F8 按下] 停止录音，正在识别...", end="", flush=True)
                    stop_recording.set()
                else:
                    # 未在录音，开始录音
                    if recording_thread[0] is not None and recording_thread[0].is_alive():
                        # 如果之前的线程还在运行，先停止它
                        stop_recording.set()
                        recording_thread[0].join(timeout=0.5)
                    print("\r[F8 按下] 开始录音...", end="", flush=True)
                    recording_active[0] = True
                    t = threading.Thread(target=do_record, daemon=True)
                    recording_thread[0] = t
                    t.start()
                return

            if hasattr(key, "char") and key.char is not None:
                c = key.char
                with lock:
                    buffer.append(c)
                _redraw_line(prompt, buffer, lock)
        except Exception as e:
            print(f"\n[按键监听错误] {e}", flush=True)

    def on_release(key) -> None:
        # F8 现在通过 on_press 处理，不需要在 on_release 中处理
        pass

    voice_handler = threading.Thread(target=voice_result_handler, daemon=True)
    voice_handler.start()

    sys.stdout.write(prompt)
    sys.stdout.flush()
    
    # 检查 pynput 是否可用
    if keyboard is None:
        print("\n[错误] pynput 未安装，无法监听按键。请运行: pip install pynput")
        return input(prompt).strip()
    
    try:
        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.start()
        
        # 等待一小段时间确保监听器启动
        time.sleep(0.1)
        
        if not listener.running:
            print("\n[警告] 按键监听器未能启动。可能需要管理员权限（Windows）或权限设置（Linux/Mac）")
            print("  提示：在 Windows 上，尝试以管理员身份运行程序")
            return input(prompt).strip()
        
        line = result_queue.get()
        if isinstance(line, _CtrlCSentinel):
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"\n[错误] 按键监听异常: {e}")
        print("  提示：可能需要管理员权限或检查 pynput 安装")
        return input(prompt).strip()
    finally:
        try:
            listener.stop()
        except Exception:
            pass
        try:
            voice_result_queue.put(None)
        except Exception:
            pass

    return line.strip() if line else None


def close_browser():
    """关闭浏览器（如果已打开）"""
    global _MAIN_LOOP
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if loop.is_running():
            # 如果循环正在运行，创建任务
            import asyncio as aio
            task = aio.create_task(_close_browser_async())
            return "浏览器关闭任务已提交"
        else:
            return loop.run_until_complete(_close_browser_async())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_close_browser_async())
        finally:
            loop.close()


# ==================== 主程序 ====================
def main():
    """主循环：同一行内可直接打字，或长按 v 说话、松手后语音自动填入，按 Enter 提交"""
    print("=" * 60)
    print("  浏览器智能助手 - 支持上下文连接的多任务自动化")
    print("  直接打字输入，或按 F8 开始录音、再按 F8 停止并识别，结果自动填入当前行，Enter 提交")
    print("=" * 60)
    print("  命令: quit/退出 结束 | clear/清空 清空历史 | history/历史 查看历史")
    print("  助手在需要时会向您提问（如登录手机号、验证码、注册账号密码等），请在终端输入回答。")
    print("=" * 60)
    
    # 检查依赖（Windows 用 msvcrt 不依赖 pynput）
    if sys.platform != "win32" and not PYNPUT_AVAILABLE:
        print("\n[警告] 非 Windows 下需 pynput 才能用 F8 语音。请运行: pip install pynput")
    elif not ASR_REALTIME_AVAILABLE:
        print("\n[警告] dashscope 未安装，F8 语音不可用。请运行: pip install dashscope")
    elif not BROWSER_LLM_API_KEY:
        print("\n[警告] 未配置 API Key，F8 语音不可用")
    else:
        print("\n[就绪] 直接打字或按 F8 录音；Ctrl+C 可中断")
    print()

    while True:
        try:
            user_input = read_line_with_voice("请输入浏览器任务 > ")
            print()
            if not user_input:
                continue

            user_input_lower = user_input.lower()

            if user_input_lower in ["quit", "exit", "退出", "q"]:
                print("程序退出！")
                close_browser()
                break

            if user_input_lower in ["clear", "清空", "重置"]:
                result = clear_conversation_history()
                print(f"  {result}")
                print()
                continue

            if user_input_lower in ["history", "历史", "h"]:
                history = get_conversation_history()
                if history:
                    print("\n【对话历史】")
                    for idx, (task, result) in enumerate(history, 1):
                        print(f"  {idx}. 任务：{task}")
                        print(f"     结果：{result}\n")
                else:
                    print("  暂无对话历史")
                print()
                continue
            
            print("\n[浏览器自动化执行中...]")
            result = browser_agent(user_input, include_context=True)
            print(f"  {result}")
            print()
            
        except KeyboardInterrupt:
            print("\n程序退出！")
            break
        except Exception as e:
            print(f"[错误] {e}")
            print()


if __name__ == "__main__":
    main()
