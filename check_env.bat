@echo off
chcp 65001 >nul
echo ========================================
echo AI面试系统 - 环境检查工具
echo ========================================
echo.

REM 检查Python
echo [检查1/6] Python安装...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ Python未安装或未添加到PATH
) else (
    echo   ✓ Python已安装
    python --version
)
echo.

REM 检查虚拟环境
echo [检查2/6] 虚拟环境...
if exist "venv" (
    echo   ✓ 虚拟环境已创建
    if exist "venv\Scripts\python.exe" (
        echo   ✓ Python可执行文件存在
    ) else (
        echo   ⚠ 虚拟环境可能不完整
    )
) else (
    echo   ✗ 虚拟环境不存在
)
echo.

REM 检查.env文件
echo [检查3/6] .env配置文件...
if exist ".env" (
    echo   ✓ .env文件存在
    findstr /C:"DASHSCOPE_API_KEY" .env >nul
    if %errorlevel% neq 0 (
        echo   ⚠ .env文件中未找到DASHSCOPE_API_KEY
    ) else (
        echo   ✓ API密钥配置项存在
    )
) else (
    echo   ⚠ .env文件不存在（使用.env.example创建）
)
echo.

REM 检查依赖
echo [检查4/6] Python依赖包...
if exist "venv\Scripts\pip.exe" (
    call venv\Scripts\activate.bat >nul 2>&1
    pip show django >nul 2>&1
    if %errorlevel% equ 0 (
        echo   ✓ Django已安装
    ) else (
        echo   ✗ Django未安装
    )

    pip show dashscope >nul 2>&1
    if %errorlevel% equ 0 (
        echo   ✓ DashScope已安装
    ) else (
        echo   ✗ DashScope未安装
    )
) else (
    echo   ⚠ 虚拟环境不存在或pip不可用
)
echo.

REM 检查数据库迁移
echo [检查5/6] 数据库迁移...
if exist "db.sqlite3" (
    echo   ✓ SQLite数据库文件存在
) else (
    echo   ⚠ 数据库文件不存在（需要运行迁移）
)
echo.

REM 检查端口占用
echo [检查6/6] 检查8000端口...
netstat -ano | findstr ":8000" >nul 2>&1
if %errorlevel% equ 0 (
    echo   ⚠ 端口8000已被占用
) else (
    echo   ✓ 端口8000可用
)
echo.

echo ========================================
echo 检查完成
echo ========================================
echo.
echo 快速启动命令：
echo   1. 激活虚拟环境: venv\Scripts\activate
echo   2. 启动服务: python manage.py runserver
echo   3. 访问: http://localhost:8000/api/ai-interview/test/
echo.
pause
