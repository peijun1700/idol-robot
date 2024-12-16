# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify, send_from_directory
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

# 設置日誌
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.debug = True  # 開啟調試模式

# 設置最大上傳文件大小為 16MB
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# 獲取當前目錄的絕對路徑
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
logger.info(f"應用程序根目錄: {BASE_DIR}")

# 音檔資料夾名稱（使用絕對路徑）
AUDIO_FOLDER = os.path.join(BASE_DIR, "audio_files")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
PROFILE_FOLDER = os.path.join(BASE_DIR, "profile_images")
CONFIG_FOLDER = os.path.join(BASE_DIR, "user_configs")

# 確保所有需要的目錄都存在
for folder in [AUDIO_FOLDER, UPLOAD_FOLDER, PROFILE_FOLDER, CONFIG_FOLDER]:
    try:
        os.makedirs(folder, exist_ok=True)
        logger.info(f"確保目錄存在: {folder}")
    except Exception as e:
        logger.error(f"創建目錄失敗 {folder}: {str(e)}")

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
        config_path = os.path.join(CONFIG_FOLDER, f"{user_id}.json")
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
        config_path = os.path.join(CONFIG_FOLDER, f"{user_id}.json")
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
    try:
        user_id = request.args.get('user_id', 'default')
        logger.info(f"訪問首頁，用戶ID: {user_id}")
        
        user_config = UserConfig.load_or_create(user_id)
        logger.info(f"加載用戶配置: {user_config.__dict__}")
        
        # 獲取用戶特定的音檔列表
        user_audio_folder = os.path.join(AUDIO_FOLDER, user_id)
        user_upload_folder = os.path.join(UPLOAD_FOLDER, user_id)
        
        try:
            os.makedirs(user_audio_folder, exist_ok=True)
            os.makedirs(user_upload_folder, exist_ok=True)
            
            audio_files = [os.path.splitext(f)[0] for f in os.listdir(user_audio_folder) if f.endswith(".m4a")]
            upload_files = [os.path.splitext(f)[0] for f in os.listdir(user_upload_folder) if f.endswith(".m4a")]
            all_responses = list(set(audio_files + upload_files))
            
            logger.info(f"找到的音頻文件: {all_responses}")
            
            return render_template('index.html', 
                                 audio_files=all_responses,
                                 user_id=user_id,
                                 idol_name=user_config.idol_name,
                                 profile_image=user_config.profile_image,
                                 theme_color=user_config.theme_color,
                                 secondary_color=user_config.secondary_color,
                                 button_color=user_config.button_color)
        except Exception as e:
            logger.error(f"處理音頻文件時出錯: {str(e)}")
            return render_template('index.html',
                                 audio_files=[],
                                 user_id=user_id,
                                 idol_name=user_config.idol_name,
                                 profile_image=user_config.profile_image,
                                 theme_color=user_config.theme_color,
                                 secondary_color=user_config.secondary_color,
                                 button_color=user_config.button_color)
    except Exception as e:
        logger.error(f"首頁路由出錯: {str(e)}")
        return str(e), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'audio' not in request.files:
            logger.error("No audio file in request")
            return jsonify({'error': '沒有收到音檔'}), 400
        
        file = request.files['audio']
        if not allowed_file(file.filename, ALLOWED_EXTENSIONS):
            return jsonify({'error': '不支援的檔案格式'}), 400
        
        command = request.form.get('command', '').strip()
        if not command:
            logger.error("No command provided")
            return jsonify({'error': '請提供指令名稱'}), 400
        
        user_id = request.form.get('user_id', 'default')
        user_audio_folder = os.path.join(AUDIO_FOLDER, user_id)
        os.makedirs(user_audio_folder, exist_ok=True)
        
        if file:
            filename = "{0}.m4a".format(command)
            file_path = os.path.join(user_audio_folder, filename)
            
            try:
                file.save(file_path)
                logger.info(f"Successfully uploaded file: {filename}")
                return jsonify({
                    'success': True,
                    'message': '成功上傳音檔: {0}'.format(filename)
                })
            except Exception as e:
                logger.error(f"Error saving file: {str(e)}")
                return jsonify({'error': '上傳失敗: {0}'.format(str(e))}), 500
        
        return jsonify({'error': '無效的檔案'}), 400
    except Exception as e:
        logger.error(f"Error in upload route: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/recognize', methods=['POST'])
def recognize_audio():
    try:
        data = request.get_json()
        if not data or 'command' not in data:
            return jsonify({'error': '沒有收到指令'}), 400
        
        command = data['command'].lower()
        logger.info(f"Received command: {command}")
        
        # 如果說"結束"，返回特殊標記
        if "結束" in command:
            return jsonify({
                'success': True,
                'command': command,
                'action': 'stop'
            })
        
        user_id = data.get('user_id', 'default')
        user_audio_folder = os.path.join(AUDIO_FOLDER, user_id)
        user_upload_folder = os.path.join(UPLOAD_FOLDER, user_id)
        
        # 獲取用戶特定的音檔列表
        audio_files = [os.path.splitext(f)[0] for f in os.listdir(user_audio_folder) if f.endswith(".m4a")]
        upload_files = [os.path.splitext(f)[0] for f in os.listdir(user_upload_folder) if f.endswith(".m4a")]
        all_responses = list(set(audio_files + upload_files))
        
        # 直接匹配或模糊匹配
        if command in all_responses:
            file_name = command
        else:
            file_name = get_closest_match(command, all_responses)
        
        if file_name:
            logger.info(f"Found matching file: {file_name}")
            return jsonify({
                'success': True,
                'command': command,
                'file_name': file_name,
                'action': 'play'
            })
        else:
            logger.warning(f"No matching file found for command: {command}")
            return jsonify({
                'success': False,
                'error': '找不到與 "{0}" 匹配的音檔'.format(command)
            })
    
    except Exception as e:
        logger.error(f"Error in recognize route: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_commands')
def get_commands():
    try:
        user_id = request.args.get('user_id', 'default')
        user_audio_folder = os.path.join(AUDIO_FOLDER, user_id)
        user_upload_folder = os.path.join(UPLOAD_FOLDER, user_id)
        
        # 獲取用戶特定的音檔列表
        audio_files = [os.path.splitext(f)[0] for f in os.listdir(user_audio_folder) if f.endswith(".m4a")]
        upload_files = [os.path.splitext(f)[0] for f in os.listdir(user_upload_folder) if f.endswith(".m4a")]
        all_commands = list(set(audio_files + upload_files))  # 去重
        all_commands.sort()  # 按字母順序排序
        
        logger.debug(f"Available commands: {all_commands}")
        return jsonify({
            'success': True,
            'commands': all_commands
        })
    except Exception as e:
        logger.error(f"Error getting commands: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/play/<filename>')
def play_audio(filename):
    try:
        user_id = request.args.get('user_id', 'default')
        user_audio_folder = os.path.join(AUDIO_FOLDER, user_id)
        user_upload_folder = os.path.join(UPLOAD_FOLDER, user_id)
        
        # 先檢查上傳資料夾
        upload_path = os.path.join(user_upload_folder, "{0}.m4a".format(filename))
        if os.path.exists(upload_path):
            file_path = upload_path
        else:
            # 如果上傳資料夾沒有，則檢查原始資料夾
            file_path = os.path.join(user_audio_folder, "{0}.m4a".format(filename))
        
        if os.path.exists(file_path):
            try:
                # 讀取音檔
                with open(file_path, 'rb') as f:
                    audio_data = f.read()
                # 將音檔轉換為base64格式
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                logger.info(f"Successfully loaded audio file: {filename}")
                return jsonify({'success': True, 'audio_data': audio_base64})
            except Exception as e:
                logger.error(f"Error reading audio file: {str(e)}")
                return jsonify({'error': '播放音檔時發生錯誤: {0}'.format(str(e))}), 500
        else:
            logger.error(f"Audio file not found: {filename}")
            return jsonify({'error': '找不到音檔: {0}.m4a'.format(filename)}), 404
    except Exception as e:
        logger.error(f"Error in play route: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/upload_profile', methods=['POST'])
def upload_profile():
    try:
        if 'profile' not in request.files:
            logger.error("No profile image in request")
            return jsonify({'error': '沒有收到圖片'}), 400
        
        file = request.files['profile']
        if not allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
            return jsonify({'error': '不支援的檔案格式'}), 400
        
        user_id = request.form.get('user_id', 'default')
        
        if file:
            # 確保檔案名稱固定為 profile.jpg
            filename = "profile.jpg"
            file_path = os.path.join(PROFILE_FOLDER, filename)
            
            try:
                # 儲存上傳的圖片
                file.save(file_path)
                logger.info(f"Successfully uploaded profile image")
                
                # 更新用戶配置
                user_config = UserConfig.load_or_create(user_id)
                user_config.profile_image = f'/profile_images/{filename}'
                user_config.save(user_id)
                
                return jsonify({
                    'success': True,
                    'message': '成功更新頭像',
                    'image_url': user_config.profile_image
                })
            except Exception as e:
                logger.error(f"Error saving profile image: {str(e)}")
                return jsonify({'error': '上傳失敗: {0}'.format(str(e))}), 500
        
        return jsonify({'error': '無效的檔案'}), 400
    except Exception as e:
        logger.error(f"Error in profile upload: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/profile_images/<filename>')
def profile_image(filename):
    return send_from_directory(PROFILE_FOLDER, filename)

@app.route('/user_profile_images/<user_id>/<filename>')
def serve_profile_image(user_id, filename):
    return send_from_directory(os.path.join(PROFILE_FOLDER, user_id), filename)

@app.route('/update_config', methods=['POST'])
def update_config():
    try:
        user_id = request.args.get('user_id', 'default')
        idol_name = request.form.get('idol_name', '未命名')
        theme_color = request.form.get('theme_color', '#FF69B4')
        secondary_color = request.form.get('secondary_color', '#fff5f8')
        button_color = request.form.get('button_color', '#FF69B4')

        # 處理圖片上傳
        profile_image_path = ''
        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file and allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
                # 確保用戶的圖片目錄存在
                user_profile_folder = os.path.join(PROFILE_FOLDER, user_id)
                os.makedirs(user_profile_folder, exist_ok=True)
                
                # 生成安全的文件名
                filename = secure_filename(file.filename)
                file_path = os.path.join(user_profile_folder, filename)
                
                # 保存文件
                file.save(file_path)
                
                # 生成相對路徑用於顯示
                profile_image_path = f'/user_profile_images/{user_id}/{filename}'
                logger.info(f"保存了新的個人圖片: {profile_image_path}")

        user_config = UserConfig(
            idol_name=idol_name,
            profile_image=profile_image_path if profile_image_path else request.form.get('profile_image', ''),
            theme_color=theme_color,
            secondary_color=secondary_color,
            button_color=button_color
        )
        user_config.save(user_id)
        
        logger.info(f"更新用戶配置成功: {user_config.__dict__}")
        return jsonify({
            'success': True, 
            'message': '設置已更新',
            'profile_image': profile_image_path if profile_image_path else None
        })
    except Exception as e:
        logger.error(f"更新用戶配置失敗: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

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
