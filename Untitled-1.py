import os
import speech_recognition as sr
from pydub import AudioSegment
from pydub.playback import play
import time
import threading
import difflib  # 用于模糊匹配

# 音檔資料夾名稱
AUDIO_FOLDER = "audio_files"

# 初始化語音辨識器
recognizer = sr.Recognizer()

def listen_and_recognize():
    """使用麥克風接收語音並轉換成文字"""
    with sr.Microphone() as source:
        print("請開始說話...")
        try:
            audio = recognizer.listen(source, timeout=3)  # 延長等待時間
            command = recognizer.recognize_google(audio, language="zh-TW")  # 使用中文辨識
            print(f"辨識到指令: {command}")
            return command.lower()  # 轉為小寫以避免大小寫問題
        except sr.UnknownValueError:
            print("無法辨識語音，請再試一次！")
            return None
        except sr.RequestError:
            print("語音辨識服務出現問題，請檢查網路連線！")
            return None

def get_closest_match(command, file_list):
    """模糊匹配最接近的文件名"""
    matches = difflib.get_close_matches(command, file_list, n=1, cutoff=0.6)
    if matches:
        return matches[0]  # 返回最接近的匹配项
    return None

def play_audio(command):
    """根據指令播放對應的音檔"""
    # 取得資料夾內的所有音檔名稱（不包含路徑）
    audio_files = [os.path.splitext(f)[0] for f in os.listdir(AUDIO_FOLDER) if f.endswith(".m4a")]
    
    # 嘗試直接匹配
    if command in audio_files:
        file_name = command
    else:
        # 使用模糊匹配尋找最接近的檔案
        file_name = get_closest_match(command, audio_files)
        if file_name:
            print(f"找不到完全匹配的檔案，使用最接近的匹配: {file_name}.m4a")
        else:
            print(f"找不到與 '{command}' 匹配的音檔")
            return

    file_path = os.path.join(AUDIO_FOLDER, f"{file_name}.m4a")
    if os.path.exists(file_path):
        print(f"播放音檔: {file_name}.m4a")
        try:
            # 讀取 m4a 檔案並轉換為音頻對象
            audio = AudioSegment.from_file(file_path, format="m4a")
            play(audio)  # 播放音檔
        except Exception as e:
            print(f"播放音檔時發生錯誤: {e}")
    else:
        print(f"找不到對應音檔: {file_name}.m4a")

def main():
    print("語音互動系統啟動中... (說 '結束' 來關閉程式)")
    while True:
        command = listen_and_recognize()
        if command:
            if command == "結束":
                print("系統已結束，謝謝使用！")
                break
            # 使用線程非同步播放音檔，讓程式能夠更快繼續進行
            threading.Thread(target=play_audio, args=(command,)).start()
            # 確保在播放音檔時不會再次接收語音
            time.sleep(2)  # 給予一點延遲，避免立刻再觸發語音辨識

if __name__ == "__main__":
    main()
 