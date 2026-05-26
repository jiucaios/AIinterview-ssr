# AI面试系统 - 快速开始指南

## 🎯 快速设置（推荐）

### 方式一：使用批处理脚本（Windows）

```bash
# 1. 双击运行 setup_venv.bat
# 或在命令行中执行：
setup_venv.bat
```

### 方式二：使用PowerShell脚本

```powershell
# 1. 运行PowerShell脚本
.\setup_venv.ps1

# 2. 如果遇到执行策略错误，运行：
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\setup_venv.ps1
```

---

## 📋 环境要求

- **Python**: 3.11 或更高版本
- **操作系统**: Windows 10/11, Linux, macOS
- **网络**: 需要互联网连接以下载依赖包

---

## 🔧 手动设置步骤

如果脚本无法运行，请按以下步骤手动配置：

### 1. 检查Python版本

```bash
python --version
# 确保显示 Python 3.11.x 或更高版本
```

### 2. 创建虚拟环境

```bash
# 在项目根目录执行
python -m venv venv
```

### 3. 激活虚拟环境

**Windows (CMD):**
```cmd
venv\Scripts\activate.bat
```

**Windows (PowerShell):**
```powershell
venv\Scripts\Activate.ps1
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

### 4. 安装依赖

```bash
# 使用国内镜像（推荐）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或使用官方源
pip install -r requirements.txt
```

### 5. 配置环境变量

复制 `.env.example` 为 `.env` 并编辑：

```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

编辑 `.env` 文件，填入你的配置：

```env
DASHSCOPE_API_KEY=your_api_key_here
QWEN_MODEL=qwen-plus
QWEN_EMBEDDING_MODEL=text-embedding-v4
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```

### 6. 数据库迁移

```bash
python manage.py makemigrations ai_interview
python manage.py migrate
```

### 7. 启动服务

```bash
python manage.py runserver
```

访问 http://localhost:8000/api/ai-interview/test/

---

## 🔍 常见问题

### Q: Python命令找不到？

**解决方案：**
1. 重新安装Python
2. 勾选 "Add Python to PATH" 选项
3. 重启命令行窗口

### Q: pip安装速度慢？

**解决方案：**
```bash
# 使用国内镜像源
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q: 虚拟环境激活失败？

**Windows PowerShell:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Q: 依赖安装失败？

**检查项：**
1. Python版本是否符合要求（3.11+）
2. 网络连接是否正常
3. 尝试使用管理员权限运行

---

## 📦 已安装的主要依赖

| 包名 | 版本 | 用途 |
|------|------|------|
| Django | >=4.2,<5.0 | Web框架 |
| djangorestframework | >=3.14.0 | REST API |
| dashscope | >=1.20.0 | 千问API |
| numpy | >=1.24.0 | 数值计算 |
| pdfplumber | >=0.10.0 | PDF解析 |
| pypdfium2 | >=5.0.0 | PDF渲染 |
| python-docx | >=0.8.11 | Word处理 |
| Pillow | >=10.0.0 | 图片处理 |
| pytesseract | >=0.3.10 | OCR识别 |

---

## 🚀 验证安装

安装完成后，运行以下命令验证：

```bash
# 进入Python交互环境
python

# 检查依赖
>>> import django
>>> import rest_framework
>>> import dashscope
>>> print("✓ 所有依赖已正确安装")
```

---

## 📚 更多信息

- 项目文档：[README.md](README.md)
- 虚拟环境详情：[VIRTUAL_ENV_REQUIREMENTS.md](VIRTUAL_ENV_REQUIREMENTS.md)
- 阿里云百炼API：https://bailian.console.aliyun.com/

---

## ⚠ 注意事项

1. **不要提交 `.env` 文件**到版本控制
2. **定期更新依赖**：`pip freeze > requirements.txt`
3. **使用虚拟环境**进行开发，避免污染全局Python环境
4. **获取API密钥**：访问 https://bailian.console.aliyun.com/ 申请

---

## 🆘 获取帮助

如果遇到问题：

1. 检查Python版本：`python --version`
2. 检查pip版本：`pip --version`
3. 查看错误日志
4. 参考 [README.md](README.md) 和 [VIRTUAL_ENV_REQUIREMENTS.md](VIRTUAL_ENV_REQUIREMENTS.md)

---

**创建时间**: 2026-05-22
**最后更新**: 2026-05-22
