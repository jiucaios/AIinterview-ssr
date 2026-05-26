# AI面试（补充人才画像）模块

Django集成模块，JSON交互，实现6轮智能面试对话，生成增量人才画像。

## 🎤 语音面试功能（新增）

**2026-05-22 更新：支持语音面试！**

- ✅ **语音识别（ASR）**：候选人通过麦克风回答问题，自动转换为文字
- ✅ **语音合成（TTS）**：AI问题使用sambert-zhiying-v1模型合成语音播放
- ✅ **暂停/继续**：支持随时暂停和继续面试
- ✅ **本地录音**：浏览器内置录音功能，支持Web Speech API备用方案

详细文档请查看：[VOICE_INTERVIEW_GUIDE.md](VOICE_INTERVIEW_GUIDE.md)

### 快速开始语音面试
```bash
# Windows用户
setup_voice.bat

# 或手动安装
pip install -r requirements.txt
python test_voice.py  # 测试语音功能
python manage.py runserver
```

访问：http://localhost:8000/api/ai-interview/test/

***

## 技术栈更新说明

### 重要变更（2026-05-22）

- **语音功能**：新增语音面试支持（ASR + TTS）
- **对话生成模型**：**Qwen-Plus**（当前使用，deepseek-v4-flash已切换回qwen-plus）
- **语义嵌入模型**：**text-embedding-v4**（千问API）
- **所有AI能力**：统一使用阿里云百炼（DashScope）API
- **缓存方案**：使用 **LocMemCache**（Django内置，无需额外安装）
- **新增功能**：会话重新连接（通过候选人ID恢复中断的面试）
- **提示词管理**：提示词统一存放在独立文件，便于维护
- **简历解析功能**：支持PDF、DOC/DOCX、图片（OCR）、TXT格式的简历文件解析

### 配置文件版本管理

- [.env](.env)：环境变量配置，必须实时更新
- [requirements.txt](requirements.txt)：依赖版本锁定
- [VIRTUAL\_ENV\_REQUIREMENTS.md](VIRTUAL_ENV_REQUIREMENTS.md)：虚拟环境详细信息
- [config/settings.py](config/settings.py)：Django、DRF、模板、缓存与模型配置
- [ai_interview/test_tool.html](ai_interview/test_tool.html)：前端测试工具与简历上传入口（支持语音面试）
- [ai_interview/services/prompts.py](ai_interview/services/prompts.py)：提示词配置文件
- [ai_interview/services/voice_service.py](ai_interview/services/voice_service.py)：语音服务模块（TTS/ASR）
- [test_voice.py](test_voice.py)：语音功能测试脚本
- [VOICE_INTERVIEW_GUIDE.md](VOICE_INTERVIEW_GUIDE.md)：语音面试详细文档

***

## 目录结构

```
AIinterview/
├── config/                 # Django配置
│   ├── __init__.py
│   ├── settings.py          # Django/DRF/模板/缓存配置
│   ├── urls.py              # 项目根路由
│   ├── wsgi.py
│   └── asgi.py
├── ai_interview/           # AI面试应用
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py           # TalentProfile模型
│   ├── views.py            # API视图
│   ├── urls.py             # 应用路由
│   ├── test_tool.html      # 前端测试页面（简历上传/JSON请求）
│   └── services/
│       ├── __init__.py
│       ├── session_manager.py    # 会话管理（LocMemCache）
│       ├── dialogue_engine.py    # 6轮对话引擎
│       ├── qwen_service.py        # 千问API集成
│       ├── embedding_service.py   # 语义相似度（text-embedding-v4）
│       ├── hard_field_detector.py # 硬性字段检测
│       ├── prompts.py             # 提示词配置
│       └── resume_parser.py       # 简历解析服务（支持PDF/DOC/DOCX/图片OCR/TXT）
├── manage.py
├── requirements.txt
├── VIRTUAL_ENV_REQUIREMENTS.md
├── start_server.bat
├── .env
└── README.md
```

## 安装

### 1. 虚拟环境设置（推荐）

详细的虚拟环境配置请参考 [VIRTUAL\_ENV\_REQUIREMENTS.md](VIRTUAL_ENV_REQUIREMENTS.md)

```bash
# 创建虚拟环境
python -m venv venv

# Windows激活
venv\Scripts\activate

# Linux/Mac激活
source venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

编辑 `.env` 文件，填入你的配置：

```env
# 千问（DashScope）API密钥
DASHSCOPE_API_KEY=your_api_key_here

# 千问对话生成模型（当前使用 deepseek-v4-flash）
QWEN_MODEL=deepseek-v4-flash

# 千问嵌入模型（推荐使用 text-embedding-v4）
QWEN_EMBEDDING_MODEL=text-embedding-v4

# 会话超时时间（秒）
SESSION_TIMEOUT=120

# Django配置
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```

### 4. 数据库迁移

```bash
python manage.py makemigrations ai_interview
python manage.py migrate
```

### 5. 启动服务

```bash
python manage.py runserver
```

**注意**：当前使用 LocMemCache，无需安装额外服务。

***

## 集成到现有Django项目

### 1. 复制应用

将 `ai_interview` 目录复制到你的Django项目

### 2. 更新 settings.py

```python
INSTALLED_APPS = [
    # ... existing apps
    'rest_framework',
    'ai_interview',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [],
        },
    },
]

# 使用LocMemCache（Django内置，无需额外配置）
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

REST_FRAMEWORK = {
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
        'rest_framework.parsers.FormParser',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'UNAUTHENTICATED_USER': None,
}

# 千问API配置
DASHSCOPE_API_KEY = 'your_api_key'
QWEN_MODEL = 'deepseek-v4-flash'
QWEN_EMBEDDING_MODEL = 'text-embedding-v4'
SESSION_TIMEOUT = 120
```

### 3. 配置 URLs

在你的 `urls.py` 中添加路由：

```python
from django.urls import path, include

urlpatterns = [
    # ... existing urls
    path('api/ai-interview/', include('ai_interview.urls')),
]
```

### 4. 添加 .gitignore

确保以下内容不被提交到版本控制：

```
.env
venv/
*.sqlite3
__pycache__/
*.pyc
```

***

## 前端测试工具

### 测试页面地址

启动服务后，访问：`http://localhost:8000/api/ai-interview/test/`

### 字段填写说明（括号内为填写示例）

| 字段名        | 说明                   | 填写示例                      |
| ---------- | -------------------- | ------------------------- |
| **候选人ID**  | 唯一标识符，用于关联人才库和重新连接会话 | CAND\_001                 |
| **姓名**     | 候选人的真实姓名             | 张三                        |
| **目标岗位**   | 应聘的职位名称              | 高级Python工程师               |
| **岗位需求**   | 该岗位的具体要求             | 需要有大规模系统经验                |
| **技能列表**   | 逗号分隔                 | Python, Django, 机器学习      |
| **项目经历**   | 候选人参与的项目             | 电商平台项目...                 |
| **英语等级**   | 从下拉选择                | 英语六级                      |
| **证书**     | 逗号分隔                 | PMP, AWS                  |
| **必问硬性字段** | 需要在面试中验证的字段，逗号分隔     | english\_level, cert\_pmp |
| **自定义提问**  | 动态添加自定义问题，AI会提问并记录   | 见下方说明                     |

### 自定义提问功能（动态键值对）

**用途**：添加自定义问题到面试中，AI会自动提问并记录回答

**填写方式**：

- **键名**：字段标识（如：driving\_license）
- **键值**：要提问的问题（如：您会开车吗？）

**示例**：

```
键名：driving_license
键值：您会开车吗？是否有驾照？
```

AI会在面试对话中自动提问"您会开车吗？是否有驾照？"，并将回答记录在最终画像中。

### 重新连接功能

**场景**：面试过程中因网络中断或长时间未回复导致会话断开

**使用方式**：

1. 在测试工具中填写相同的**候选人ID**
2. 点击"生成JSON"按钮
3. 点击"🔄 重新连接"按钮

**原理**：系统会根据候选人ID查找缓存中的会话记录，恢复之前的对话历史，并继续面试。

### 生成的JSON结构

```json
{
    "candidate_id": "CAND_001",
    "resume": {
        "name": "张三",
        "skills": ["Python", "Django"],
        "projects": "电商平台项目...",
        "english_level": "英语六级",
        "certificates": ["PMP", "AWS"]
    },
    "job_config": {
        "title": "高级Python工程师",
        "requirements": "需要有大规模系统经验"
    },
    "required_hard_fields": ["english_level", "cert_pmp"],
    "custom_questions": {
        "driving_license": "您会开车吗？是否有驾照？",
        "other_cert": "是否有其他专业证书？"
    }
}
```

### 最终画像记录

面试完成后，自定义提问的回答会记录在画像中：

```json
{
    "candidate_id": "CAND_001",
    "session_id": "uuid-string",
    "custom_question_results": {
        "driving_license": {
            "question": "您会开车吗？是否有驾照？",
            "answer": "我有C1驾照，已经有3年驾龄",
            "confidence": 0.9
        },
        "other_cert": {
            "question": "是否有其他专业证书？",
            "answer": "我还考取了AWS解决方案架构师认证",
            "confidence": 0.85
        }
    }
}
```

***

## API调用示例

### 1. 启动面试会话

**请求：**

```bash
POST /api/ai-interview/session/
Content-Type: application/json

{
    "action": "start",
    "candidate_id": "CAND_001",
    "resume": {
        "name": "张三",
        "skills": ["Python", "Django", "机器学习"],
        "projects": [
            {
                "name": "电商平台",
                "role": "后端开发",
                "description": "负责订单系统和用户模块开发"
            }
        ]
    },
    "job_config": {
        "title": "高级Python工程师",
        "special_requirements": ["需要有大规模系统经验"]
    },
    "required_hard_fields": ["english_level", "cert_pmp", "years_experience"],
    "custom_questions": {
        "driving_license": "您会开车吗？是否有驾照？"
    }
}
```

**响应：**

```json
{
    "session_id": "uuid-string",
    "question": "请详细介绍一下您的英语水平？",
    "round": 1,
    "round_name": "hard_field",
    "total_rounds": 6,
    "reasked": false
}
```

### 2. 提交回答

**请求：**

```bash
POST /api/ai-interview/session/
Content-Type: application/json

{
    "action": "answer",
    "session_id": "uuid-string",
    "answer": "我在项目中主导了订单系统架构设计，使用微服务架构..."
}
```

**响应：**

```json
{
    "session_id": "uuid-string",
    "question": "您提到的微服务架构，具体使用了哪些技术栈？",
    "round": 2,
    "round_name": "role_verification",
    "total_rounds": 6,
    "reasked": false
}
```

### 3. 重新连接会话

**请求：**

```bash
POST /api/ai-interview/session/
Content-Type: application/json

{
    "action": "resume",
    "candidate_id": "CAND_001"
}
```

**响应：**

```json
{
    "session_id": "uuid-string",
    "question": "您提到的微服务架构，具体使用了哪些技术栈？",
    "round": 2,
    "round_name": "role_verification",
    "total_rounds": 6,
    "resumed": true,
    "dialogue_history": [...],
    "message": "会话已重新连接"
}
```

### 4. 获取会话详情

**请求：**

```bash
GET /api/ai-interview/session/{session_id}/
```

**响应：**

```json
{
    "session_id": "uuid-string",
    "candidate_id": "CAND_001",
    "current_round": 3,
    "state": "active",
    "dialogue_history": [...],
    "hard_fields_missing": ["cert_pmp"],
    "hard_fields_collected": {
        "english_level": {"value": "英语六级", "verified": true}
    },
    "project_roles_collected": {...}
}
```

### 5. 结束会话（获取最终画像）

当所有轮次完成或超时时，响应会包含最终画像：

```json
{
    "candidate_id": "CAND_001",
    "session_id": "uuid-string",
    "session_incomplete": false,
    "hard_fields_results": {
        "english_level": {"value": "英语六级", "verified": true, "source": "interview"}
    },
    "project_role_results": {
        "projects": {
            "电商平台": {
                "role_level": "leading",
                "depth_info": {
                    "technical_contributions": ["架构", "设计", "开发"],
                    "complexity_level": "high"
                }
            }
        }
    },
    "custom_question_results": {
        "driving_license": {
            "question": "您会开车吗？是否有驾照？",
            "answer": "我有C1驾照，已经有3年驾龄",
            "confidence": 0.9
        }
    },
    "confidence_score": 0.85,
    "profile_id": "uuid-string",
    "message": "会话结束"
}
```

***

## 6轮对话规则

| 轮次 | 维度      | 说明             |
| -- | ------- | -------------- |
| 1  | 硬性指标补全  | 根据缺失的必问硬性字段提问  |
| 2  | 项目角色真实性 | 验证候选人在项目中的真实角色 |
| 3  | 项目角色深度  | 深入探测技术贡献和深度    |
| 4  | 技能偏差    | 检测技能描述与实际能力的偏差 |
| 5  | 语言逻辑    | 测试表达逻辑性和思维清晰度  |
| 6  | 岗位特殊要求  | 验证岗位特定要求的真实性   |

**注**：自定义提问会在6轮对话结束后根据配置添加到面试中。

***

## 兜底策略

- **回答过短(<5字)**：追问一次
- **语义相似度<0.3**：重新表述问题
- **连续2次无效**：跳过该维度
- **超时120秒+10秒等待**：结束会话，保存已有信息
- **AI内容检测**：检测第一人称、典型句式、时长内容，标记可信度
- **会话中断恢复**：支持通过候选人ID重新连接

***

## 模型配置说明

### DeepSeek-V4-Flash

- **用途**：对话生成、问题生成、回答质量评估
- **特点**：高性能、响应快、专业领域知识丰富
- **配置位置**：`.env` 中的 `QWEN_MODEL` 和 `config/settings.py`

### text-embedding-v4

- **用途**：语义相似度计算、回答相关性判断
- **特点**：高准确度、支持长文本
- **配置位置**：`.env` 中的 `QWEN_EMBEDDING_MODEL` 和 `config/settings.py`

***

## 提示词配置文件

### 文件位置

`ai_interview/services/prompts.py`

### 文件结构

```python
# 系统提示词
INTERVIEWER_SYSTEM_PROMPT = "..."       # 面试官角色定义
REPHRASE_SYSTEM_PROMPT = "..."           # 问题重表述提示词
RESUME_PARSER_SYSTEM_PROMPT = "..."      # 简历解析系统提示词

# 轮次提示词模板
HARD_FIELD_PROMPT = "..."                # 硬性指标补全
ROLE_VERIFICATION_PROMPT = "..."         # 项目角色真实性
ROLE_DEPTH_PROMPT = "..."                # 项目角色深度
SKILL_DEVIATION_PROMPT = "..."          # 技能偏差检测
LANGUAGE_LOGIC_PROMPT = "..."           # 语言逻辑测试
SPECIAL_REQUIREMENT_PROMPT = "..."      # 岗位特殊要求
RESUME_PARSER_PROMPT = "..."             # 简历解析提示词

# 辅助提示词
ANSWER_VALIDATION_PROMPT = "..."        # 回答质量评估
PROFILE_SUMMARY_PROMPT = "..."          # 画像总结

# 配置字典
PROMPT_CONFIG = {
    'interviewer_system': INTERVIEWER_SYSTEM_PROMPT,
    'resume_parser_system': RESUME_PARSER_SYSTEM_PROMPT,
    'resume_parser': RESUME_PARSER_PROMPT,
    # ... 其他提示词
}

# 获取提示词函数
def get_prompt(prompt_name: str, **kwargs) -> str:
    """获取指定名称的提示词，支持参数替换"""
```

### 提示词管理规范

1. **集中管理**：所有提示词统一存放在此文件中
2. **参数化**：使用 `{placeholder}` 格式支持动态参数替换
3. **注释说明**：每个提示词应有清晰的注释说明用途
4. **版本控制**：修改提示词时需更新文档

***

## 数据存储

- **原始简历**：在 `TalentProfile.raw_resume` 中存储，不修改原简历表
- **增量画像**：在 `TalentProfile.hard_fields_results` 和 `project_role_results` 中增量存储
- **自定义提问结果**：存储在 `custom_question_results` 字段中
- **会话状态**：存储在LocMemCache中，支持断点续答
- **候选人索引**：会话与候选人ID建立关联，支持重新连接

***

## 缓存配置说明

### 当前方案：LocMemCache

项目当前使用 Django 内置的 **LocMemCache**（本地内存缓存）：

```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}
```

<br />

***

## 开发文档维护规范

### 文档实时更新要求

每次修改代码或配置时，必须同步更新以下文件：

1. **[.env](.env)** - 更新环境变量
2. **[requirements.txt](requirements.txt)** - 锁定依赖版本
3. **[VIRTUAL\_ENV\_REQUIREMENTS.md](VIRTUAL_ENV_REQUIREMENTS.md)** - 更新虚拟环境信息
4. **[config/settings.py](config/settings.py)** - 更新 Django、DRF、缓存与模板配置
5. **[ai\_interview/test_tool.html](ai_interview/test_tool.html)** - 更新前端测试入口和请求配置
6. **[README.md](README.md)** - 更新使用说明和技术变更
7. **[ai\_interview/services/prompts.py](ai_interview/services/prompts.py)** - 更新提示词配置

### 版本管理

- 每次重大功能更新必须在 README 开头记录变更说明
- 日期格式统一使用：YYYY-MM-DD
- 保留变更历史，便于追溯

### 代码注释要求

- 所有公共类和方法必须添加中文注释
- 复杂逻辑必须添加行内注释
- API参数和返回值必须有明确说明

***

## 常见问题

### Q: 会话状态存储在哪里？

A: 会话状态存储在 LocMemCache 中（当前方案），默认内存存储，重启服务后数据丢失。

### Q: 自定义提问如何工作？

A: 在测试工具中添加自定义提问（键值对），AI会在面试中自动提问这些问题，并将回答记录在最终画像的 `custom_question_results` 字段中。

### Q: 如何重新连接中断的会话？

A: 使用相同的候选人ID，通过 `action: "resume"` API 或测试工具的"重新连接"按钮恢复会话。

### Q: 提示词保存在哪里？

A: 提示词统一存放在 `ai_interview/services/prompts.py` 文件中，便于集中管理和维护。

***

## 技术支持

如有问题，请查看：

- [VIRTUAL\_ENV\_REQUIREMENTS.md](VIRTUAL_ENV_REQUIREMENTS.md) - 虚拟环境详细信息
- [requirements.txt](requirements.txt) - 依赖版本列表
- [ai\_interview/services/prompts.py](ai_interview/services/prompts.py) - 提示词配置
- 代码注释 - 各模块的详细说明
