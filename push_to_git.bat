@echo off
echo ===============================================
echo          推送代码到 GitHub
echo ===============================================
echo.

cd /d d:\campus\AIinterview

echo 检查当前目录...
echo 当前目录: %cd%
echo.

echo 检查 .env 是否在 .gitignore 中...
findstr /i ".env" .gitignore >nul
if %errorlevel% equ 0 (
    echo ✓ .env 文件已在 .gitignore 中
) else (
    echo ✗ .env 文件不在 .gitignore 中，请先更新 .gitignore
    pause
    exit /b 1
)
echo.

echo 初始化 Git 仓库...
git init
echo.

echo 添加远程仓库...
git remote add origin https://github.com/jiucaios/AIinterview.git
echo.

echo 检查远程仓库配置...
git remote -v
echo.

echo 添加所有文件到暂存区...
git add .
echo.

echo 查看暂存的文件...
git status
echo.

echo 提交代码...
git commit -m "Initial commit: AI面试系统 - 简历解析与智能面试对话引擎"
echo.

echo 设置主分支...
git branch -M main
echo.

echo 推送到远程仓库...
git push -u origin main
echo.

echo 操作完成！
pause