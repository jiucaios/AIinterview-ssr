# AI面试系统 - 虚拟环境设置脚本
# 最后更新：2026-05-22

param(
    [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "AI面试系统 - 虚拟环境配置向导" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查Python版本
Write-Host "[1/6] 检查Python安装..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Python not found in PATH" }
    Write-Host "✓ 发现Python: $pythonVersion" -ForegroundColor Green

    # 提取版本号
    if ($pythonVersion -match "Python (\d+)\.(\d+)") {
        $major = [int]$matches[1]
        $minor = [int]$matches[2]

        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
            Write-Host "✗ Python版本过低！需要Python 3.11或更高版本" -ForegroundColor Red
            Write-Host "  当前版本: $pythonVersion" -ForegroundColor Red
            Write-Host "  请访问 https://www.python.org/downloads/ 下载最新版本" -ForegroundColor Yellow
            exit 1
        }
    }
} catch {
    Write-Host "✗ 未找到Python或Python未添加到PATH" -ForegroundColor Red
    Write-Host ""
    Write-Host "请先安装Python 3.11或更高版本：" -ForegroundColor Yellow
    Write-Host "  1. 访问 https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host "  2. 下载Python 3.11或更高版本" -ForegroundColor Cyan
    Write-Host "  3. 安装时勾选 'Add Python to PATH'" -ForegroundColor Cyan
    Write-Host "  4. 重新运行此脚本" -ForegroundColor Cyan
    exit 1
}

# 检查虚拟环境
Write-Host ""
Write-Host "[2/6] 检查虚拟环境..." -ForegroundColor Yellow
$VenvPath = Join-Path $ProjectRoot "venv"

if (Test-Path $VenvPath) {
    if ($ForceRecreate) {
        Write-Host "正在删除旧虚拟环境..." -ForegroundColor Yellow
        Remove-Item -Path $VenvPath -Recurse -Force
        Write-Host "✓ 已删除旧虚拟环境" -ForegroundColor Green
    } else {
        Write-Host "✓ 虚拟环境已存在: $VenvPath" -ForegroundColor Green
        Write-Host "  使用 -ForceRecreate 参数可重新创建" -ForegroundColor Gray
    }
}

# 创建虚拟环境
if (-not (Test-Path $VenvPath) -or $ForceRecreate) {
    Write-Host ""
    Write-Host "[3/6] 创建虚拟环境..." -ForegroundColor Yellow
    python -m venv $VenvPath
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ 虚拟环境创建成功" -ForegroundColor Green
    } else {
        Write-Host "✗ 虚拟环境创建失败" -ForegroundColor Red
        exit 1
    }
}

# 激活虚拟环境
Write-Host ""
Write-Host "[4/6] 激活虚拟环境并安装依赖..." -ForegroundColor Yellow
$VenvActivate = Join-Path $VenvPath "Scripts\Activate.ps1"
$VenvPip = Join-Path $VenvPath "Scripts\pip.exe"

if (-not (Test-Path $VenvPip)) {
    Write-Host "✗ 虚拟环境不完整，pip未找到" -ForegroundColor Red
    exit 1
}

# 升级pip
Write-Host "  升级pip..." -ForegroundColor Gray
& $VenvPip install --upgrade pip

# 安装依赖
Write-Host ""
Write-Host "  安装项目依赖包..." -ForegroundColor Gray
$RequirementsFile = Join-Path $ProjectRoot "requirements.txt"

if (Test-Path $RequirementsFile) {
    & $VenvPip install -r $RequirementsFile
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ 依赖安装成功" -ForegroundColor Green
    } else {
        Write-Host "  ✗ 依赖安装失败" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  ⚠ requirements.txt 文件未找到" -ForegroundColor Yellow
}

# 配置环境变量文件
Write-Host ""
Write-Host "[5/6] 配置环境变量..." -ForegroundColor Yellow
$EnvExample = Join-Path $ProjectRoot ".env.example"
$EnvFile = Join-Path $ProjectRoot ".env"

if (-not (Test-Path $EnvFile) -and Test-Path $EnvExample) {
    Write-Host "  正在创建 .env 文件..." -ForegroundColor Gray
    Copy-Item $EnvExample $EnvFile
    Write-Host "  ✓ 已创建 .env 文件" -ForegroundColor Green
    Write-Host "  ⚠ 请编辑 .env 文件，填入你的 DASHSCOPE_API_KEY" -ForegroundColor Yellow
} elseif (Test-Path $EnvFile) {
    Write-Host "  ✓ .env 文件已存在" -ForegroundColor Green
} else {
    Write-Host "  ⚠ .env.example 文件未找到" -ForegroundColor Yellow
}

# 数据库迁移
Write-Host ""
Write-Host "[6/6] 数据库设置..." -ForegroundColor Yellow
Write-Host "  运行数据库迁移..." -ForegroundColor Gray
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$VenvManagePy = Join-Path $ProjectRoot "manage.py"

if (Test-Path $VenvManagePy) {
    # 确保在正确的目录
    Push-Location $ProjectRoot
    & $VenvPython $VenvManagePy makemigrations ai_interview
    & $VenvPython $VenvManagePy migrate
    Pop-Location

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ 数据库迁移成功" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ 数据库迁移可能有问题，请检查配置" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "✓ 虚拟环境配置完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "下一步操作：" -ForegroundColor Yellow
Write-Host "  1. 编辑 .env 文件，填入 DASHSCOPE_API_KEY" -ForegroundColor Cyan
Write-Host "  2. 激活虚拟环境: venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host "  3. 启动服务: python manage.py runserver" -ForegroundColor Cyan
Write-Host ""
