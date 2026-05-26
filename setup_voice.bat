@echo off
chcp 65001 >nul
echo ========================================
echo AI面试系统 - 语音功能安装和测试
echo ========================================
echo.

echo [1/4] 检查虚拟环境...
if exist "venv\Scripts\activate.bat" (
    echo ✓ 虚拟环境存在
    call venv\Scripts\activate.bat
) else (
    echo ✗ 虚拟环境不存在，请先运行 setup_venv.ps1
    pause
    exit /b 1
)

echo.
echo [2/4] 安装语音相关依赖...
pip install SpeechRecognition pyaudio wave
if errorlevel 1 (
    echo ✗ 依赖安装失败
    pause
    exit /b 1
)
echo ✓ 依赖安装成功

echo.
echo [3/4] 运行语音功能测试...
python test_voice.py
if errorlevel 1 (
    echo.
    echo ⚠ 部分测试失败，但不影响基本使用
    echo TTS功能需要有效的DASHSCOPE_API_KEY
)

echo.
echo [4/4] 启动开发服务器...
echo.
echo ========================================
echo 服务器即将启动
echo 访问地址: http://localhost:8000/api/ai-interview/test/
echo ========================================
echo.
echo 提示：
echo 1. 首次使用录音功能时，浏览器会请求麦克风权限
echo 2. 请允许麦克风权限以使用语音识别功能
echo 3. 确保在localhost或HTTPS环境下使用
echo.

python manage.py runserver

pause
