
# 虚拟环境配置要求

> **重要提示**：每次修改环境配置或依赖版本时，必须更新此文档！
> 最后更新：2026-05-15

---

## Python版本要求

```
Python 3.11.x 或更高版本
```

**检查Python版本：**

```bash
python --version
```

---

## 虚拟环境设置

### 1. 创建虚拟环境

```bash
# Windows
python -m venv venv

# Linux/Mac
python3 -m venv venv
```

### 2. 激活虚拟环境

**Windows (PowerShell):**

```powershell
venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**

```cmd
venv\Scripts\activate.bat
```

**Linux/Mac:**

```bash
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

---

## 已安装包列表（版本锁定）

| 包名 | 版本要求 | 用途 |
|------|----------|------|
| Django | >=4.2, <5.0 | Web框架 |
| djangorestframework | >=3.14.0 | REST API框架 |
| dashscope | >=1.20.0 | 千问API SDK |
| python-dotenv | >=1.0.0 | 环境变量管理 |
| numpy | >=1.24.0 | 数值计算 |
| pdfplumber | >=0.10.0 | PDF解析 |
| pypdfium2 | >=5.0.0 | PDF文本提取与页面渲染 |
| python-docx | >=0.8.11 | Word文档处理 |
| Pillow | >=10.0.0 | 图片处理 |
| pytesseract | >=0.3.10 | OCR文字识别 |

---

## 系统环境要求

当前会话缓存使用 Django 内置 **LocMemCache**，不需要额外安装 Redis 服务。

如需解析图片简历，系统需安装 Tesseract OCR，并配置中文语言包 `chi_sim`。

---

## 环境变量配置

创建或编辑项目根目录下的 `.env` 文件：

```env
# ========================================
# 千问API配置
# ========================================

# 阿里云百炼API密钥（必须配置）
# 获取地址：https://bailian.console.aliyun.com/
DASHSCOPE_API_KEY=your_api_key_here

# ========================================
# 模型配置
# ========================================

# 对话生成模型
# 推荐：deepseek-v4-flash
QWEN_MODEL=deepseek-v4-flash

# 语义嵌入模型
# 推荐：text-embedding-v4
QWEN_EMBEDDING_MODEL=text-embedding-v4

# ========================================
# 会话配置
# ========================================

# 会话超时时间（秒）
SESSION_TIMEOUT=120

# ========================================
# Django配置
# ========================================

# 调试模式
DEBUG=True

# 允许的主机
ALLOWED_HOSTS=localhost,127.0.0.1
```

---

## Django缓存配置说明

项目使用 LocMemCache 作为 Django 缓存后端，配置位于 `config/settings.py`：

```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}
```

**缓存用途：**
- 存储会话状态（支持断点续答）
- 临时存储面试对话历史
- 提高系统响应速度

---

## 导出当前环境

如果你修改了依赖版本，请更新 `requirements.txt`：

```bash
# 导出当前环境的所有依赖
pip freeze > requirements.txt

# 或者只导出项目直接依赖（推荐）
# 手动更新 requirements.txt 中的版本号
```

---

## 虚拟环境清理

如需重新创建虚拟环境：

```bash
# 1. 退出虚拟环境
deactivate

# 2. 删除虚拟环境目录
# Windows
rmdir /s /q venv

# Linux/Mac
rm -rf venv

# 3. 重新创建虚拟环境
# 按照上面的步骤重新创建和安装依赖
```

---

## 常见问题

### Q: Windows下无法激活虚拟环境？
A: 可能需要修改PowerShell执行策略：

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Q: pip安装速度慢？
A: 使用国内镜像源：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q: 如何验证所有依赖正确安装？
A: 运行：

```bash
pip list
```

检查所有包是否已正确安装。

## 版本变更记录

| 日期 | 变更内容 | 更新人 |
|------|----------|--------|
| 2026-05-15 | 同步当前依赖清单、LocMemCache缓存配置和相关文档目录说明 | AI Assistant |
| 2026-05-14 | 初始版本，配置DeepSeek-V4-Flash和text-embedding-v4 | AI Assistant |

---

## 注意事项

1. **不要将 `.env` 文件提交到版本控制**，它包含敏感信息
2. **定期更新依赖版本**，但要在测试环境先验证
3. **保持开发、测试、生产环境一致**
4. **每次环境变更必须更新此文档**
5. **当前缓存方案为LocMemCache，重启Django应用后会话缓存会清空**
