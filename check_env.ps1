# AI面试系统 - 环境检查脚本
$ErrorActionPreference = "Continue"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "AI面试系统 - 环境检查工具" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[检查1/6] Python安装..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] Python已安装: $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] Python未安装或未添加到PATH" -ForegroundColor Red
}
Write-Host ""

Write-Host "[检查2/6] 虚拟环境..." -ForegroundColor Yellow
$VenvPath = "venv"
if (Test-Path $VenvPath) {
    Write-Host "  [OK] 虚拟环境已创建" -ForegroundColor Green
    if (Test-Path "$VenvPath\Scripts\python.exe") {
        Write-Host "  [OK] Python可执行文件存在" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] 虚拟环境可能不完整" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [FAIL] 虚拟环境不存在" -ForegroundColor Red
}
Write-Host ""

Write-Host "[检查3/6] .env配置文件..." -ForegroundColor Yellow
if (Test-Path ".env") {
    Write-Host "  [OK] .env文件存在" -ForegroundColor Green
    $content = Get-Content ".env" -Raw
    if ($content -match "DASHSCOPE_API_KEY=your_") {
        Write-Host "  [WARN] API密钥未配置（请修改.env文件）" -ForegroundColor Yellow
    } elseif ($content -match "DASHSCOPE_API_KEY=") {
        Write-Host "  [OK] API密钥已配置" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] .env文件中未找到DASHSCOPE_API_KEY" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [WARN] .env文件不存在（使用.env.example创建）" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "[检查4/6] Python依赖包..." -ForegroundColor Yellow
if (Test-Path "venv\Scripts\pip.exe") {
    $VenvPython = "venv\Scripts\python.exe"
    $checkDjango = & $VenvPython -m pip show django 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] Django已安装" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] Django未安装" -ForegroundColor Red
    }

    $checkDashscope = & $VenvPython -m pip show dashscope 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] DashScope已安装" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] DashScope未安装" -ForegroundColor Red
    }
} else {
    Write-Host "  [WARN] 虚拟环境不存在或pip不可用" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "[检查5/6] 数据库迁移..." -ForegroundColor Yellow
if (Test-Path "db.sqlite3") {
    Write-Host "  [OK] SQLite数据库文件存在" -ForegroundColor Green
} else {
    Write-Host "  [WARN] 数据库文件不存在（需要运行迁移）" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "[检查6/6] 检查8000端口..." -ForegroundColor Yellow
$portCheck = netstat -ano | Select-String ":8000"
if ($portCheck) {
    Write-Host "  [WARN] 端口8000已被占用" -ForegroundColor Yellow
} else {
    Write-Host "  [OK] 端口8000可用" -ForegroundColor Green
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "检查完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "下一步操作：" -ForegroundColor Yellow
Write-Host "  1. 运行 setup_venv.ps1 配置虚拟环境（如果虚拟环境不存在）" -ForegroundColor Cyan
Write-Host "  2. 编辑 .env 文件，填入 DASHSCOPE_API_KEY" -ForegroundColor Cyan
Write-Host "  3. 激活虚拟环境: venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host "  4. 启动服务: python manage.py runserver" -ForegroundColor Cyan
Write-Host "  5. 访问测试页面: http://localhost:8000/api/ai-interview/test/" -ForegroundColor Cyan
Write-Host ""
