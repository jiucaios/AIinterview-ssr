@echo off
chcp 65001 >nul
echo ===============================================
echo          推送代码到 GitHub
echo ===============================================
echo.

cd /d d:\campus\AIinterview

echo [1/6] 检查 .env 是否在 .gitignore 中...
findstr /i ".env" .gitignore >nul
if %errorlevel% equ 0 (
    echo     ✓ .env 文件已在 .gitignore 中，不会被提交
) else (
    echo     ✗ 警告: .env 文件不在 .gitignore 中
    echo     请按任意键继续（不推荐）或按 Ctrl+C 退出
    pause >nul
)
echo.

echo [2/6] 初始化 Git 仓库（如果尚未初始化）...
git init
echo     ✓ 完成
echo.

echo [3/6] 添加远程仓库...
git remote add origin https://github.com/jiucaios/AIinterview.git
echo     ✓ 完成
echo.

echo [4/6] 查看暂存状态（确保 .env 未被追踪）...
git add .
git status
echo.

echo [5/6] 提交代码...
git commit -m "AI面试系统 - 简历解析与智能面试对话引擎"
echo     ✓ 完成
echo.

echo [6/6] 推送到远程仓库...
git branch -M main
git push -u origin main
echo     ✓ 完成
echo.

echo ===============================================
echo          推送完成！
echo ===============================================
echo.
echo 代码已推送到: https://github.com/jiucaios/AIinterview
echo.
pause