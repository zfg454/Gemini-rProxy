from io import BytesIO
import base64
from PIL import Image
from flask import jsonify
import logging
import json
import re
import os
import requests
import google.generativeai as genai
logger = logging.getLogger(__name__)


request_counts = {}

password = str(os.environ.get('password', 'your_password'))

def authenticate_request(request):
    auth_header = request.headers.get('Authorization')

    if not auth_header:
        return False, jsonify({'error': '缺少Authorization请求头'}), 401

    try:
        auth_type, pass_word = auth_header.split(' ', 1)
    except ValueError:
        return False, jsonify({'error': 'Authorization请求头格式错误'}), 401

    if auth_type.lower() != 'bearer':
        return False, jsonify({'error': 'Authorization类型必须为Bearer'}), 401

    if pass_word != password:
        return False, jsonify({'error': '未授权'}), 401

    return True, None, None

def process_messages_for_gemini(messages):
    gemini_history = []
    errors = []
    for message in messages:
        role = message.get('role')
        content = message.get('content')

        if isinstance(content, str):
            if role == 'system':
                gemini_history.append({"role": "user", "parts": [content]})
            elif role == 'user':
                gemini_history.append({"role": "user", "parts": [content]})
            elif role == 'assistant':
                gemini_history.append({"role": "model", "parts": [content]})
            else:
                errors.append(f"Invalid role: {role}")
        elif isinstance(content, list):
            parts = []
            for item in content:
                if item.get('type') == 'text':
                    parts.append({"text": item.get('text')})  
                elif item.get('type') == 'image_url':
                    image_data = item.get('image_url', {}).get('url', '')
                    if image_data.startswith('data:image/'):

                        try:
                            mime_type, base64_data = image_data.split(';')[0].split(':')[1], image_data.split(',')[1]
                            parts.append({
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64_data
                                }
                            })
                        except (IndexError, ValueError):
                            errors.append(f"Invalid data URI for image: {image_data}")
                    else:
                        errors.append(f"Invalid image URL format for item: {item}")
                elif item.get('type') == 'file_url':
                    file_data = item.get('file_url', {}).get('url', '')
                    if file_data.startswith('data:'):

                        try:
                            mime_type, base64_data = file_data.split(';')[0].split(':')[1], file_data.split(',')[1]
                            parts.append({
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64_data
                                }
                            })
                        except (IndexError, ValueError):
                            errors.append(f"Invalid data URI for file: {file_data}")
                    else:
                        errors.append(f"Invalid file URL format for item: {item}")

            if parts: 
                if role in ['user', 'system']:
                    gemini_history.append({"role": "user", "parts": parts})
                elif role in ['assistant']:
                    gemini_history.append({"role": "model", "parts": parts})
                else:
                    errors.append(f"Invalid role: {role}")

    if gemini_history:
        user_message = gemini_history[-1]
        gemini_history = gemini_history[:-1]
    else:
        user_message = {"role": "user", "parts": [""]}

    if errors:
        return gemini_history, user_message, (jsonify({'error': errors}), 400)
    else:
        return gemini_history, user_message, None