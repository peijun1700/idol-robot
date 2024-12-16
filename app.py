# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify, send_from_directory, session
import os
import speech_recognition as sr
from pydub import AudioSegment
import difflib
import threading
import base64
import io
import logging
import json
from werkzeug.utils import secure_filename
import uuid

# 設置日誌
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)  # 為 session 添加密鑰
app.debug = True  # 開啟調試模式

# 設置上傳文件的目錄
BASE_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
UPLOAD_FOLDER = os.path.join(BASE_FOLDER, 'uploads')
AUDIO_FOLDER = os.path.join(BASE_FOLDER, 'audio')
PROFILE_FOLDER = os.path.join(BASE_FOLDER, 'profiles')
CONFIG_FOLDER = os.path.join(BASE_FOLDER, 'config')

def get_user_folders(user_id):
    """為每個用戶創建獨立的文件夾"""
    user_upload = os.path.join(UPLOAD_FOLDER, user_id)
    user_audio = os.path.join(AUDIO_FOLDER, user_id)
    user_profile = os.path.join(PROFILE_FOLDER, user_id)
    user_config = os.path.join(CONFIG_FOLDER, user_id)
    
    # 確保用戶目錄存在
    for directory in [user_upload, user_audio, user_profile, user_config]:
        os.makedirs(directory, exist_ok=True)
    
    return user_upload, user_audio, user_profile, user_config

def get_user_id():
    """從 session 或 cookie 獲取用戶ID，如果不存在則創建新的"""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    return session['user_id']

# 設置最大上傳文件大小為 16MB
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# 允許的文件類型
ALLOWED_EXTENSIONS = {'m4a', 'mp3', 'wav'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# 新增用戶配置類
class UserConfig:
    def __init__(self, idol_name="未命名", profile_image="", theme_color="#FF69B4", secondary_color="#fff5f8", button_color="#FF69B4"):
        self.idol_name = idol_name
        self.profile_image = profile_image
        self.theme_color = theme_color          # 主題顏色
        self.secondary_color = secondary_color  # 次要顏色
        self.button_color = button_color       # 按鈕顏色

    @staticmethod
    def load_or_create(user_id):
        config_path = os.path.join(CONFIG_FOLDER, user_id, f"{user_id}.json")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return UserConfig(
                    data.get('idol_name', '未命名'),
                    data.get('profile_image', ''),
                    data.get('theme_color', '#FF69B4'),
                    data.get('secondary_color', '#fff5f8'),
                    data.get('button_color', '#FF69B4')
                )
        return UserConfig()

    def save(self, user_id):
        config_path = os.path.join(CONFIG_FOLDER, user_id, f"{user_id}.json")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump({
                'idol_name': self.idol_name,
                'profile_image': self.profile_image,
                'theme_color': self.theme_color,
                'secondary_color': self.secondary_color,
                'button_color': self.button_color
            }, f, ensure_ascii=False)

# 初始化語音辨識器
recognizer = sr.Recognizer()

def get_closest_match(command, file_list):
    """模糊匹配最接近的文件名"""
    matches = difflib.get_close_matches(command, file_list, n=1, cutoff=0.6)
    if matches:
        return matches[0]
    return None

# 添加安全檢查
def allowed_file(filename, allowed_extensions):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

@app.route('/')
def index():
    user_id = get_user_id()
    user_upload, user_audio, user_profile, user_config = get_user_folders(user_id)
    
    # 讀取用戶配置
    config = UserConfig.load_or_create(user_id)
    
    # 獲取用戶的音頻文件
    audio_files = []
    if os.path.exists(user_audio):
        audio_files = [f for f in os.listdir(user_audio) if f.endswith('.mp3')]
    
    return render_template('index.html', 
                         idol_name=config.idol_name,
                         profile_image=config.profile_image,
                         theme_color=config.theme_color,
                         secondary_color=config.secondary_color,
                         button_color=config.button_color,
                         audio_files=audio_files)

@app.route('/upload', methods=['POST'])
def upload_file():
    user_id = get_user_id()
    user_upload, user_audio, _, _ = get_user_folders(user_id)
    
    if 'file' not in request.files:
        return jsonify({'error': '沒有文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '沒有選擇文件'}), 400
    
    if file and allowed_file(file.filename, {'mp3', 'wav', 'm4a'}):
        filename = secure_filename(file.filename)
        file_path = os.path.join(user_upload, filename)
        file.save(file_path)
        
        # 轉換音頻格式
        try:
            audio = AudioSegment.from_file(file_path)
            output_path = os.path.join(user_audio, os.path.splitext(filename)[0] + '.mp3')
            audio.export(output_path, format='mp3')
            os.remove(file_path)  # 刪除原始文件
            return jsonify({'message': '上傳成功'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': '不支持的文件格式'}), 400

@app.route('/recognize', methods=['POST'])
def recognize_audio():
    user_id = get_user_id()
    _, user_audio, _, _ = get_user_folders(user_id)
    
    if 'file' not in request.files:
        return jsonify({'error': '沒有文件'}), 400
        
    audio_file = request.files['file']
    if audio_file.filename == '':
        return jsonify({'error': '沒有選擇文件'}), 400
        
    if audio_file and allowed_file(audio_file.filename, {'wav'}):
        filename = secure_filename(audio_file.filename)
        temp_path = os.path.join(user_audio, 'temp_' + filename)
        audio_file.save(temp_path)
        
        try:
            with sr.AudioFile(temp_path) as source:
                audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data, language='zh-TW')
                os.remove(temp_path)
                return jsonify({'text': text}), 200
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return jsonify({'error': str(e)}), 500
            
    return jsonify({'error': '不支持的文件格式'}), 400

@app.route('/commands', methods=['GET'])
def get_commands():
    user_id = get_user_id()
    _, user_audio, _, _ = get_user_folders(user_id)
    
    command = request.args.get('command', '').lower()
    if not command:
        return jsonify({'error': '沒有提供命令'}), 400
        
    audio_files = [f for f in os.listdir(user_audio) if f.endswith('.mp3')]
    if not audio_files:
        return jsonify({'error': '沒有找到音頻文件'}), 404
        
    closest_match = get_closest_match(command, audio_files)
    return jsonify({'file': closest_match}), 200

@app.route('/audio/<path:filename>')
def play_audio(filename):
    user_id = get_user_id()
    _, user_audio, _, _ = get_user_folders(user_id)
    return send_from_directory(user_audio, filename)

@app.route('/upload_profile', methods=['POST'])
def upload_profile():
    user_id = get_user_id()
    _, _, user_profile, _ = get_user_folders(user_id)
    
    if 'profile_image' not in request.files:
        return jsonify({'error': '沒有文件'}), 400
    
    file = request.files['profile_image']
    if file.filename == '':
        return jsonify({'error': '沒有選擇文件'}), 400
    
    if file and allowed_file(file.filename, {'png', 'jpg', 'jpeg', 'gif'}):
        # 刪除舊的頭像文件
        for old_file in os.listdir(user_profile):
            os.remove(os.path.join(user_profile, old_file))
        
        filename = secure_filename(file.filename)
        file_path = os.path.join(user_profile, filename)
        file.save(file_path)
        
        # 更新配置
        config = UserConfig.load_or_create(user_id)
        config.profile_image = filename
        config.save(user_id)
        
        return jsonify({'message': '上傳成功', 'filename': filename}), 200
    
    return jsonify({'error': '不支持的文件格式'}), 400

@app.route('/profile_image/<path:filename>')
def serve_profile_image(filename):
    user_id = get_user_id()
    _, _, user_profile, _ = get_user_folders(user_id)
    return send_from_directory(user_profile, filename)

@app.route('/config', methods=['POST'])
def update_config():
    user_id = get_user_id()
    config = UserConfig.load_or_create(user_id)
    
    data = request.get_json()
    
    if 'idol_name' in data:
        config.idol_name = data['idol_name']
    if 'theme_color' in data:
        config.theme_color = data['theme_color']
    if 'secondary_color' in data:
        config.secondary_color = data['secondary_color']
    if 'button_color' in data:
        config.button_color = data['button_color']
    
    config.save(user_id)
    return jsonify({'message': '配置已更新'}), 200

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': '找不到請求的資源'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': '服務器內部錯誤'}), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': '上傳的檔案太大'}), 413

if __name__ == '__main__':
    # 確保所有必要的目錄存在
    for directory in [UPLOAD_FOLDER, AUDIO_FOLDER, PROFILE_FOLDER, CONFIG_FOLDER]:
        os.makedirs(directory, exist_ok=True)
    # 使用環境變量中的端口，如果沒有則使用5001
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
