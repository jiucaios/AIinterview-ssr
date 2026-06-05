# AI面试系统

基于Django框架构建的智能AI面试系统，支持语音面试、简历解析、实时对话等功能。

## 功能特性

### 🎯 核心功能
- **智能面试**：基于大语言模型的自动化面试流程
- **语音交互**：支持语音识别(ASR)和语音合成(TTS)
- **简历解析**：支持PDF、DOC/DOCX、图片(OCR)、TXT格式
- **画像生成**：自动生成候选人能力画像
- **报告分析**：完整的面试报告和评分分析

### 🔄 面试类型

#### 初次面试（六轮结构化）
- **硬性指标补全**：验证候选人基本条件（学历、经验、证书等）
- **项目角色真实性**：验证项目经历的真实性
- **项目角色深度**：考察技术深度和专业能力
- **技能偏差验证**：验证技能与岗位要求的匹配度
- **语言逻辑能力**：评估表达能力和逻辑思维
- **自定义问题**：HR自定义问题（可选）

#### 面谈模式（开放对话）
- 以HR输入的**招聘要求**为最高优先级
- 职级和简历作为参考信息
- Omni模型完全主导对话流程
- 根据招聘要求自主提问和判断
- 面试结束时说"面谈结束"

#### 两种模式对比
| 维度 | 初次面试 | 面谈模式 |
|------|---------|---------|
| 结构 | 六轮固定流程 | 开放对话 |
| 主导 | 系统控制轮次 | Omni模型主导 |
| 适用 | 标准化评估 | 灵活沟通 |
| 结束 | 六轮完成 | Omni判断结束 |

### 📊 技术栈
- **后端**：Django + Django REST Framework
- **前端**：原生HTML/CSS/JavaScript
- **AI服务**：阿里云通义千问（Qwen系列模型）
- **实时通信**：WebSocket + Omni实时语音服务

---

## 项目结构

```
AIinterview-main/
├── config/                    # Django配置
│   ├── settings.py           # 应用配置
│   ├── urls.py               # 全局路由
│   └── asgi.py/wsgi.py       # 服务入口
├── ai_interview/             # 核心应用
│   ├── views/                # API视图（按业务解耦）
│   │   ├── candidate.py      # 候选人相关API
│   │   ├── hr.py             # HR管理API
│   │   ├── interview.py      # 面试会话API
│   │   ├── report.py         # 报告API
│   │   └── external.py       # 外部接口
│   ├── services/             # 业务服务层
│   │   ├── session_manager.py # 会话管理
│   │   ├── omni_stream_service.py # Omni实时服务
│   │   ├── qwen_service.py   # 文本模型服务
│   │   ├── prompts.py        # Prompt模板
│   │   └── resume_parser.py  # 简历解析
│   ├── consumers.py          # WebSocket消费者
│   ├── models.py             # 数据库模型
│   └── templates/            # HTML页面
├── scripts/                  # 辅助脚本
├── .env                      # 环境变量
├── requirements.txt          # 依赖列表
└── manage.py                 # Django管理入口
```

---

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境（Windows）
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并配置：

```env
# 阿里云DashScope API Key
DASHSCOPE_API_KEY=your_api_key_here

# 模型配置
QWEN_MODEL=qwen3.5-omni-plus
QWEN_REALTIME_MODEL=qwen3.5-omni-plus-realtime
QWEN_EMBEDDING_MODEL=text-embedding-v4

# Django配置
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```

### 3. 数据库迁移

```bash
python manage.py makemigrations
python manage.py migrate
```

### 4. 启动服务

```bash
# 开发模式
python manage.py runserver

# HTTPS模式（需要证书）
python manage.py runsslserver 0.0.0.0:443 --certificate cert.pem --key key.pem
```

---

## 访问地址

| 页面 | 地址 | 说明 |
|------|------|------|
| HR管理后台 | http://localhost:8000/ | 创建面试、管理候选人 |
| 候选人入口 | http://localhost:8000/api/interview/welcome/ | 候选人面试入口 |
| 面试报告 | http://localhost:8000/api/ai-interview/hr/candidates/interview-report/ | 查看面试报告 |

---

## API接口

### 面试会话
- `POST /api/ai-interview/session/` - 创建/继续面试会话
- `GET /api/ai-interview/session/{session_id}/` - 获取会话详情

### HR管理
- `POST /api/ai-interview/hr/candidates/create/` - 创建候选人
- `GET /api/ai-interview/hr/candidates/` - 获取候选人列表
- `DELETE /api/ai-interview/hr/candidates/{candidate_id}/` - 删除候选人

### 外部接口
- `POST /api/external/ai-session/create/` - 外部系统创建面试

---

## 面试流程

```
HR创建面试 → 生成面试链接 → 候选人访问 → 身份验证 → 开始面试 → 语音交互 → 面试结束 → 生成报告
```

### 六轮面试结构
1. **硬性指标补全** - 验证基本条件
2. **项目角色真实性** - 验证项目经历
3. **项目角色深度** - 考察技术深度
4. **技能偏差验证** - 验证技能匹配度
5. **语言逻辑能力** - 评估表达能力
6. **自定义问题** - HR自定义问题

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端层                             │
│  HR管理页 │ 候选人面试页 │ 报告页面                      │
└───────────────────────────┬───────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                        应用层                             │
│  Django Views │ WebSocket Consumers │ REST API          │
└───────────────────────────┬───────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                        服务层                             │
│  Omni实时服务 │ Qwen文本服务 │ 会话管理 │ 简历解析      │
└───────────────────────────┬───────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                        数据层                             │
│              SQLite数据库 │ 内存缓存                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 部署说明

### 开发环境
- 使用 `runserver` 启动开发服务器
- 使用 `runsslserver` 启动HTTPS开发服务器

### 生产环境
- 推荐使用 Nginx + Gunicorn
- 配置 Let's Encrypt SSL证书
- 使用 Redis 替代内存缓存

---

## 许可证

MIT License