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
    
    if 'audio' not in request.files:
        return jsonify({'error': '沒有文件'}), 400
    
    file = request.files['audio']
    command = request.form.get('command', '').strip()
    
    if file.filename == '' or not command:
        return jsonify({'error': '沒有選擇文件或沒有指令名稱'}), 400
    
    if file and allowed_file(file.filename, {'mp3', 'wav', 'm4a'}):
        filename = f"{command}.mp3"
        temp_path = os.path.join(user_upload, secure_filename(file.filename))
        file.save(temp_path)
        
        try:
            # 轉換音頻格式
            audio = AudioSegment.from_file(temp_path)
            output_path = os.path.join(user_audio, filename)
            audio.export(output_path, format='mp3')
            os.remove(temp_path)  # 刪除臨時文件
            return jsonify({'message': '上傳成功'}), 200
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': '不支持的文件格式'}), 400

@app.route('/recognize', methods=['POST'])
def recognize_audio():
    data = request.get_json()
    if not data or 'command' not in data:
        return jsonify({'error': '沒有收到指令'}), 400
    
    command = data['command'].lower()
    user_id = get_user_id()
    _, user_audio, _, _ = get_user_folders(user_id)
    
    # 如果說"結束"，返回特殊標記
    if "結束" in command:
        return jsonify({
            'success': True,
            'command': command,
            'action': 'stop'
        })
    
    # 獲取用戶的音頻文件
    audio_files = [os.path.splitext(f)[0] for f in os.listdir(user_audio) if f.endswith('.mp3')]
    
    # 直接匹配或模糊匹配
    if command in audio_files:
        file_name = command
    else:
        file_name = get_closest_match(command, audio_files)
    
    if file_name:
        return jsonify({
            'success': True,
            'command': command,
            'file_name': file_name,
            'action': 'play'
        })
    else:
        return jsonify({
            'success': False,
            'error': f'找不到與 "{command}" 匹配的音檔'
        })

@app.route('/play/<filename>')
def play_audio(filename):
    user_id = get_user_id()
    _, user_audio, _, _ = get_user_folders(user_id)
    
    file_path = os.path.join(user_audio, f"{filename}.mp3")
    
    if os.path.exists(file_path):
        try:
            with open(file_path, 'rb') as f:
                audio_data = f.read()
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            return jsonify({'success': True, 'audio_data': audio_base64})
        except Exception as e:
            return jsonify({'error': f'播放音檔時發生錯誤: {str(e)}'}), 500
    else:
        return jsonify({'error': f'找不到音檔: {filename}.mp3'}), 404

@app.route('/get_commands')
def get_commands():
    user_id = get_user_id()
    _, user_audio, _, _ = get_user_folders(user_id)
    
    audio_files = [os.path.splitext(f)[0] for f in os.listdir(user_audio) if f.endswith('.mp3')]
    audio_files.sort()
    
    return jsonify({
        'success': True,
        'commands': audio_files
    })

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

@app.route('/update_config', methods=['POST'])
def update_config():
    user_id = get_user_id()
    _, _, user_profile, _ = get_user_folders(user_id)
    config = UserConfig.load_or_create(user_id)
    
    # 處理基本設置
    config.idol_name = request.form.get('idol_name', config.idol_name)
    config.theme_color = request.form.get('theme_color', config.theme_color)
    config.secondary_color = request.form.get('secondary_color', config.secondary_color)
    config.button_color = request.form.get('button_color', config.button_color)
    
    # 處理頭像上傳
    if 'profile_image' in request.files:
        file = request.files['profile_image']
        if file and file.filename != '' and allowed_file(file.filename, {'png', 'jpg', 'jpeg', 'gif'}):
            # 刪除舊的頭像文件
            for old_file in os.listdir(user_profile):
                old_path = os.path.join(user_profile, old_file)
                if os.path.isfile(old_path):
                    os.remove(old_path)
            
            # 保存新頭像
            filename = secure_filename(file.filename)
            file_path = os.path.join(user_profile, filename)
            file.save(file_path)
            config.profile_image = filename
    
    # 保存設置
    config.save(user_id)
    
    return jsonify({
        'success': True,
        'message': '設置已更新',
        'profile_image': f'/profile_image/{config.profile_image}' if config.profile_image else None
    }), 200

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
