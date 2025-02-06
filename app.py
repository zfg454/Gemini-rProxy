from flask import Flask, request, jsonify, Response, stream_with_context, render_template_string
from google.generativeai.types import BlockedPromptException, StopCandidateException, generation_types
from google.api_core.exceptions import InvalidArgument, ResourceExhausted, Aborted, InternalServerError, ServiceUnavailable, PermissionDenied
import google.generativeai as genai
import json
import os
import re
import logging
import func
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import time
import requests
from collections import deque
import random
from urllib.parse import urlparse
from requests.utils import get_environ_proxies
from func import authenticate_request, process_messages_for_gemini

os.environ['TZ'] = 'Asia/Shanghai'

app = Flask(__name__)

app.secret_key = os.urandom(24)

formatter = logging.Formatter('%(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)

MAX_RETRIES = int(os.environ.get('MaxRetries', 3))
MAX_REQUESTS = int(os.environ.get('MaxRequests', 2))
LIMIT_WINDOW = int(os.environ.get('LimitWindow', 60))
RETRY_DELAY = 1
MAX_RETRY_DELAY = 16

request_counts = {}

api_key_blacklist = set()
api_key_blacklist_duration = 60

# 核心优势
safety_settings = [
    {
        "category": "HARM_CATEGORY_HARASSMENT",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_HATE_SPEECH",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
        "threshold": "BLOCK_NONE"
    },
]

# 从 env.json 或 .env 加载环境变量
def load_config():
    config = {}
    try:
        with open("env.json", "r") as f:
            config = json.load(f)
            # 处理 KeyArray 中的换行符
            if "KeyArray" in config:
                config["KeyArray"] = config["KeyArray"].splitlines()
    except FileNotFoundError:
        from dotenv import load_dotenv
        load_dotenv()
        config = {key: os.environ.get(key) for key in ["KeyArray", "MaxRetries", "MaxRequests", "LimitWindow", "password", "PORT"]}
        #处理KeyArray中的换行符
        if "KeyArray" in config and config["KeyArray"]:
            config["KeyArray"] = config["KeyArray"].splitlines()
    return config

config = load_config()

def get_system_proxy(url="http://example.com"):  # get_environ_proxies 需要一个 URL 参数
    """
    获取系统代理设置。
    优先使用环境变量中的代理设置，如果没有设置，则尝试自动检测。
    """
    proxy = {}

    # 1. 优先从环境变量读取
    http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
    https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')

    if http_proxy:
        proxy['http'] = http_proxy
    if https_proxy:
        proxy['https'] = https_proxy

    # 2. 如果环境变量没有设置，尝试自动检测
    if not proxy:
        try:
            # 使用 requests.utils.get_environ_proxies()
            proxy = get_environ_proxies(url)
        except:
            # 在某些系统或配置下，get_environ_proxies() 可能会失败
            pass

    return proxy

class APIKeyManager:
    def __init__(self):
        # self.api_keys = re.findall(r"AIzaSy[a-zA-Z0-9_-]{33}", os.environ.get('KeyArray'))
        #如果config["KeyArray"]是一个列表
        if isinstance(config["KeyArray"], list):
            self.api_keys = [key for key in config["KeyArray"] if re.match(r"AIzaSy[a-zA-Z0-9_-]{33}", key)]
        else: #否则按照原方法进行
            self.api_keys = re.findall(r"AIzaSy[a-zA-Z0-9_-]{33}", os.environ.get('KeyArray'))
        self.current_index = random.randint(0, len(self.api_keys) - 1)

    def get_available_key(self):
        num_keys = len(self.api_keys)
        for _ in range(num_keys):
            if self.current_index >= num_keys:
                self.current_index = 0
            current_key = self.api_keys[self.current_index]
            self.current_index += 1

            if current_key not in api_key_blacklist:
                return current_key

        logger.error("所有API key都已耗尽或被暂时禁用，请重新配置或稍后重试")
        return None

    def show_all_keys(self):
        logger.info(f"当前可用API key个数: {len(self.api_keys)} ")
        for i, api_key in enumerate(self.api_keys):
            logger.info(f"API Key{i}: {api_key[:11]}...")

    def blacklist_key(self, key):
        logger.warning(f"{key[:11]} → 暂时禁用 {api_key_blacklist_duration} 秒")
        api_key_blacklist.add(key)

        scheduler.add_job(lambda: api_key_blacklist.discard(key), 'date', run_date=datetime.now() + timedelta(seconds=api_key_blacklist_duration))

key_manager = APIKeyManager()
key_manager.show_all_keys()
current_api_key = key_manager.get_available_key()

def switch_api_key():
    global current_api_key
    key = key_manager.get_available_key()
    if key:
      current_api_key = key
      logger.info(f"API key 替换为 → {current_api_key[:11]}...")
    else:
      logger.error("API key 替换失败，所有API key都已耗尽或被暂时禁用，请重新配置或稍后重试")

logger.info(f"当前 API key: {current_api_key[:11]}...")

GEMINI_MODELS = [
    {"id": "gemini-1.5-flash-8b-latest"},
    {"id": "gemini-1.5-flash-8b-exp-0924"},
    {"id": "gemini-1.5-flash-latest"},
    {"id": "gemini-1.5-flash-exp-0827"},
    {"id": "gemini-1.5-pro-latest"},
    {"id": "gemini-1.5-pro-exp-0827"},
    {"id": "learnlm-1.5-pro-experimental"},
    {"id": "gemini-exp-1114"},
    {"id": "gemini-exp-1121"},
    {"id": "gemini-exp-1206"},
    {"id": "gemini-2.0-flash-exp"},
    {"id": "gemini-2.0-flash-thinking-exp-1219"},
    {"id": "gemini-2.0-pro-exp"},
    {"id": "gemini-2.0-pro-exp-02-05"}
]

#print("Loaded Configuration:", config)  # 打印配置


# 设置环境变量
os.environ['TZ'] = 'Asia/Shanghai'
os.environ['KeyArray'] = config.get('KeyArray', '') if isinstance(config.get("KeyArray"), str) else "\n".join(config.get("KeyArray", []))
os.environ['MaxRetries'] = str(config.get('MaxRetries', 3))
os.environ['MaxRequests'] = str(config.get('MaxRequests', 2))
os.environ['LimitWindow'] = str(config.get('LimitWindow', 60))
os.environ['password'] = config.get('password', '')
os.environ["PORT"] = str(config.get("PORT", 7860))

@app.route('/')
def index():
    github_url = "https://github.com/your_username/your_repository"  # 替换成你的 GitHub 仓库地址
    models_html = "<ul>"
    for model in GEMINI_MODELS:
        models_html += f"<li>{model['id']}</li>"
    models_html += "</ul>"

    html_template = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Gemini Proxy</title>
</head>
<body>
<h1>Gemini Proxy</h1>
<p>这是一个 Google Gemini 模型的代理服务。</p>
<p>GitHub 仓库: <a href="{github_url}" target="_blank">{github_url}</a></p>
<h2>支持的模型</h2>
{models_html}
</body>
</html>
    """
    return render_template_string(html_template)

def is_within_rate_limit(api_key):
    now = datetime.now()
    if api_key not in request_counts:
        request_counts[api_key] = deque()

    while request_counts[api_key] and request_counts[api_key][0] < now - timedelta(seconds=LIMIT_WINDOW):
        request_counts[api_key].popleft()

    if len(request_counts[api_key]) >= MAX_REQUESTS:
        earliest_request_time = request_counts[api_key][0]
        wait_time = (earliest_request_time + timedelta(seconds=LIMIT_WINDOW)) - now
        return False, wait_time.total_seconds()
    else:
        return True, 0

def increment_request_count(api_key):
    now = datetime.now()
    if api_key not in request_counts:
        request_counts[api_key] = deque()
    request_counts[api_key].append(now)

def handle_api_error(error, attempt):
    if attempt > MAX_RETRIES:
        logger.error(f"{MAX_RETRIES} 次尝试后仍然失败，请修改预设或输入")
        return 0, jsonify({
                'error': {
                    'message': f"{MAX_RETRIES} 次尝试后仍然失败，请修改预设或输入",
                    'type': 'max_retries_exceeded'
                }
        })

    if isinstance(error, InvalidArgument):
        logger.error(f"{current_api_key[:11]} → 无效，可能已过期或被删除")
        key_manager.blacklist_key(current_api_key)
        switch_api_key()
        return 0, None

    elif isinstance(error, ResourceExhausted):
        delay = min(RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
        logger.warning(f"{current_api_key[:11]} → 429 官方资源耗尽 → {delay} 秒后重试...")
        key_manager.blacklist_key(current_api_key)
        switch_api_key()
        time.sleep(delay)
        return 0, None

    elif isinstance(error, Aborted):
        delay = min(RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
        logger.warning(f"{current_api_key[:11]} → 操作被中止 → {delay} 秒后重试...")
        time.sleep(delay)
        return 0, None

    elif isinstance(error, InternalServerError):
        delay = min(RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
        logger.warning(f"{current_api_key[:11]} → 500 服务器内部错误 → {delay} 秒后重试...")
        time.sleep(delay)
        return 0, None

    elif isinstance(error, ServiceUnavailable):
        delay = min(RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
        logger.warning(f"{current_api_key[:11]} → 503 服务不可用 → {delay} 秒后重试...")
        time.sleep(delay)
        return 0, None

    elif isinstance(error, PermissionDenied):
        logger.error(f"{current_api_key[:11]} → 403 权限被拒绝，该 API KEY 可能已经被官方封禁")
        key_manager.blacklist_key(current_api_key)
        switch_api_key()
        return 0, None

    elif isinstance(error, StopCandidateException):
        logger.warning(f"AI输出内容被Gemini官方阻挡，代理没有得到有效回复")
        switch_api_key()
        return 0, None

    elif isinstance(error, generation_types.BlockedPromptException):
        try:
            full_reason_str = str(error.args[0])

            if "block_reason:" in full_reason_str:
                start_index = full_reason_str.find("block_reason:") + len("block_reason:")
                block_reason_str = full_reason_str[start_index:].strip()

                if block_reason_str == "SAFETY":
                    logger.warning(f"用户输入因安全原因被阻止")
                    return 1, None
                elif block_reason_str == "BLOCKLIST":
                    logger.warning(f"用户输入因包含阻止列表中的术语而被阻止")
                    return 1, None
                elif block_reason_str == "PROHIBITED_CONTENT":
                    logger.warning(f"用户输入因包含禁止内容而被阻止")
                    return 1, None
                elif block_reason_str == "OTHER":
                    logger.warning(f"用户输入因未知原因被阻止")
                    return 1, None
                else:
                    logger.warning(f"用户输入被阻止，原因未知: {block_reason_str}")
                    return 1, None
            else:
                logger.warning(f"用户输入被阻止，原因未知: {full_reason_str}")
                return 1, None

        except (IndexError, AttributeError) as e:
            logger.error(f"获取提示原因失败↙\n{e}")
            logger.error(f"提示被阻止↙\n{error}")
            return 2, None

    else:
        logger.error(f"该模型还未发布，暂时不可用，请更换模型或未来一段时间再试")
        logger.error(f"证明↙\n{error}")
        return 2, None

@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    is_authenticated, auth_error, status_code = func.authenticate_request(request)
    if not is_authenticated:
        return auth_error if auth_error else jsonify({'error': '未授权'}), status_code if status_code else 401

    request_data = request.get_json()
    messages = request_data.get('messages', [])
    model = request_data.get('model', 'gemini-2.0-flash-exp')
    temperature = request_data.get('temperature', 1)
    max_tokens = request_data.get('max_tokens', 8192)
    stream = request_data.get('stream', False)
    hint = "流式" if stream else "非流"
    logger.info(f"\n{model} [{hint}] → {current_api_key[:11]}...")

    gemini_history, user_message, error_response = func.process_messages_for_gemini(messages)

    if error_response:
        logger.error(f"处理输入消息时出错↙\n {error_response}")
        return jsonify(error_response), 400

    def do_request(current_api_key, attempt):
        isok, time = is_within_rate_limit(current_api_key)
        if not isok:
            logger.warning(f"{current_api_key[:11]} → 暂时超过限额，该API key将在 {time} 秒后启用...")
            switch_api_key()
            return 0, None

        increment_request_count(current_api_key)

        genai.configure(api_key=current_api_key)

        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens
        }

        gen_model = genai.GenerativeModel(
            model_name=model,
            generation_config=generation_config,
            safety_settings=safety_settings
        )

        try:
            if gemini_history:
                chat_session = gen_model.start_chat(history=gemini_history)
                response = chat_session.send_message(user_message, stream=stream)
            else:
                response = gen_model.generate_content(user_message, stream=stream)
            return 1, response
        except Exception as e:
            return handle_api_error(e, attempt)

    def generate(response):
        try:
            logger.info(f"流式开始...")
            for chunk in response:
                if chunk.text:
                    data = {
                        'choices': [
                            {
                                'delta': {
                                    'content': chunk.text
                                },
                                'finish_reason': None,
                                'index': 0
                            }
                        ],
                        'object': 'chat.completion.chunk'
                    }
                    yield f"data: {json.dumps(data)}\n\n"

            data = {
                        'choices': [
                            {
                                'delta': {},
                                'finish_reason': 'stop',
                                'index': 0
                            }
                        ],
                        'object': 'chat.completion.chunk'
                    }
            logger.info(f"流式结束")
            yield f"data: {json.dumps(data)}\n\n"
            logger.info(f"200!")

        except Exception:
            logger.error(f"流式输出中途被截断，请关闭流式输出或修改你的输入")
            logger.info(f"流式结束")
            error_data = {
                'error': {
                    'message': '流式输出时截断，请关闭流式输出或修改你的输入',
                    'type': 'internal_server_error'
                }
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            data = {
                        'choices': [
                            {
                                'delta': {},
                                'finish_reason': 'stop',
                                'index': 0
                            }
                        ],
                        'object': 'chat.completion.chunk'
                    }

            yield f"data: {json.dumps(data)}\n\n"

    attempt = 0
    success = 0
    response = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"第 {attempt}/{MAX_RETRIES} 次尝试 ...")
        success, response = do_request(current_api_key, attempt)

        if success == 1:
            break
        elif success == 2:

            logger.error(f"{model} 很可能暂时不可用，请更换模型或未来一段时间再试")
            response = {
                'error': {
                    'message': f'{model} 很可能暂时不可用，请更换模型或未来一段时间再试',
                    'type': 'internal_server_error'
                }
            }
            return jsonify(response), 503

    else:
        logger.error(f"{MAX_RETRIES} 次尝试均失败，请调整配置或向Moonfanz反馈")
        response = {
            'error': {
                'message': f'{MAX_RETRIES} 次尝试均失败，请调整配置或向Moonfanz反馈',
                'type': 'internal_server_error'
            }
        }
        return jsonify(response), 500 if response is not None else 503

    if stream:
        return Response(stream_with_context(generate(response)), mimetype='text/event-stream')
    else:
        try:
            text_content = response.text
        except (AttributeError, IndexError, TypeError, ValueError) as e:
            if "response.candidates is empty" in str(e):
                logger.error(f"你的输入被AI安全过滤器阻止")
                return jsonify({
                    'error': {
                        'message': '你的输入被AI安全过滤器阻止',
                        'type': 'prompt_blocked_error',
                        'details': str(e)
                    }
                }), 400
            else:
                logger.error(f"AI响应处理失败")
                return jsonify({
                    'error': {
                        'message': 'AI响应处理失败',
                        'type': 'response_processing_error'
                    }
                }), 500

        response_data = {
            'id': 'chatcmpl-xxxxxxxxxxxx',  
            'object': 'chat.completion',
            'created': int(datetime.now().timestamp()),
            'model': model,
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': text_content
                },
                'finish_reason': 'stop'
            }],
            'usage': {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'total_tokens': 0
            }
        }
        logger.info(f"200!")
        return jsonify(response_data)

@app.route('/v1/models', methods=['GET'])
def list_models():
    response = {"object": "list", "data": GEMINI_MODELS}
    return jsonify(response)

def keep_alive():
    try:
        port = int(os.environ.get('PORT', 3000))
        url = f"http://127.0.0.1:{port}/"

        # 获取系统代理
        proxies = get_system_proxy(url) # 传入 URL

        # 使用代理发送请求
        response = requests.get(url, timeout=10, proxies=proxies)
        response.raise_for_status()
        print(f"Keep alive ping successful: {response.status_code} at {time.ctime()}")
    except requests.exceptions.RequestException as e:
        print(f"Keep alive ping failed: {e} at {time.ctime()}")

if __name__ == '__main__':

    # 检查配置文件是否存在
    if not os.path.exists("env.json") and not os.path.exists(".env"):
        print("错误：未找到配置文件 (env.json 或 .env)。请创建其中一个文件，并设置必要的环境变量。")
        input("按 Enter 键退出...")  # 等待用户按键
        exit(1)  # 退出程序
    # 尝试读取
    config = load_config()
    if not config.get("KeyArray") or not config.get("password"):
        print("错误：配置文件中缺少必要的环境变量 (KeyArray 和 password)。请确保已正确设置。")
        input("按 Enter 键退出...")
        exit(1)

    # 获取并设置代理 (如果需要)
    proxies = get_system_proxy()  # 或者 get_proxy()，如果你实现了方案三
    if proxies:
        #print(proxies)
        if 'http' in proxies:
            os.environ['HTTP_PROXY'] = proxies['http']
        if 'https' in proxies:
            os.environ['HTTPS_PROXY'] = proxies['https']

    scheduler = BackgroundScheduler()

    scheduler.add_job(keep_alive, 'interval', hours=12)
    scheduler.start()

    logger.info(f"最大尝试次数/MaxRetries: {MAX_RETRIES}")
    logger.info(f"最大请求次数/MaxRequests: {MAX_REQUESTS}")
    logger.info(f"请求限额窗口/LimitWindow: {LIMIT_WINDOW} 秒")

    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 3000)))