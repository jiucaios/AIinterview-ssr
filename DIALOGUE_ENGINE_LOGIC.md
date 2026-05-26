# AI面试系统 - 后端逻辑文档

## 概述

本文档详细说明AI面试系统的后端逻辑，包括对话引擎、会话管理、轮次配置等核心组件。

---

## 核心组件

### 1. 对话引擎 (DialogueEngine)

对话引擎是面试系统的核心，负责管理整个6轮面试对话流程。

**位置**: `ai_interview/services/dialogue_engine.py`

#### 轮次配置 (ROUND_CONFIG)

```python
ROUND_CONFIG = [
    {'name': 'hard_field', 'description': '硬性指标补全', 'priority': 1},
    {'name': 'role_verification', 'description': '项目角色真实性', 'priority': 2},
    {'name': 'role_depth', 'description': '项目角色深度', 'priority': 3},
    {'name': 'skill_deviation', 'description': '技能偏差', 'priority': 4},
    {'name': 'language_logic', 'description': '语言逻辑', 'priority': 5},
    {'name': 'special_requirement', 'description': '岗位特殊要求', 'priority': 6},
]
```

#### 轮次说明

| 轮次 | 名称 | 说明 | 验证内容 |
|------|------|------|----------|
| 1 | hard_field | 硬性指标补全 | 英语等级、计算机证书、学历等必填字段 |
| 2 | role_verification | 项目角色真实性 | 验证候选人在项目中的真实角色 |
| 3 | role_depth | 项目角色深度 | 深入探测技术贡献和深度 |
| 4 | skill_deviation | 技能偏差 | 检测技能描述与实际能力的偏差 |
| 5 | language_logic | 语言逻辑 | 测试表达逻辑性和思维清晰度 |
| 6 | special_requirement | 岗位特殊要求 | **处理所有自定义问题** |

---

## 关键逻辑说明

### 1. 硬性字段处理（第一轮）

**特点**: 多个硬性字段（如英语四级、计算机证书等）统一在第一轮处理，不占用额外轮次。

```python
# 硬性字段示例
required_hard_fields = ['english_level', 'cert_computer', 'cert_pmp']

# 系统会检测简历中缺失的字段，生成一个问题询问所有缺失项
# 例如："请介绍一下您的英语水平和持有的计算机相关证书"
```

### 2. 自定义问题处理（最后一轮）

**特点**: 自定义问题全部在第六轮（special_requirement）处理，不限制问题数量，直到所有问题回答完毕才结束会话。

```python
# 自定义问题示例
custom_questions = {
    'driving_license': '您会开车吗？是否有驾照？',
    'other_cert': '是否有其他专业证书？',
    'hobby': '您有什么业余爱好？'
}

# 系统会依次提问每个自定义问题
# 只有当所有自定义问题都回答完毕后，才会结束会话
```

### 3. 处理流程图

```
用户发起面试
    ↓
创建会话 (SessionManager.create_session)
    ↓
检测缺失硬性字段 (HardFieldDetector.detect_missing_hard_fields)
    ↓
生成第一轮问题 (hard_field)
    ↓
用户回答 → 验证答案质量 → 验证通过？
    ↓ 是                    ↓ 否
存储结果              检查无效次数 ≥ 2？
    ↓                     ↓ 是 → 跳过该维度
推进轮次              重新表述问题 (reasked: True)
    ↓
...（继续后续轮次）
    ↓
第六轮 (special_requirement)
    ↓
有自定义问题？ → 是 → 提问第1个 → 回答 → 提问第2个 → ... → 提问第N个 → 结束
    ↓ 否
直接结束会话
```

---

## 会话管理 (SessionManager)

**位置**: `ai_interview/services/session_manager.py`

### 会话数据结构

```python
session_data = {
    'session_id': 'uuid-string',
    'candidate_id': 'CAND_001',
    'resume': {
        'name': '张三',
        'skills': ['Python', 'Django'],
        'projects': [...],
        # ... 其他简历信息
    },
    'job_config': {
        'title': '高级Python工程师',
        'requirements': '需要有大规模系统经验'
    },
    'required_hard_fields': ['english_level', 'cert_pmp'],
    'current_round': 0,  # 当前轮次 (0-5)
    'dialogue_history': [
        {'role': 'assistant', 'content': '问题内容', 'timestamp': 1234567890},
        {'role': 'user', 'content': '回答内容', 'timestamp': 1234567891},
    ],
    'hard_fields_missing': ['english_level'],  # 缺失的硬性字段
    'hard_fields_collected': {},  # 已收集的硬性字段
    'project_roles_collected': {},  # 项目角色验证结果
    'custom_questions': {},  # 自定义问题 {key: question}
    'custom_questions_asked': [],  # 已提问的自定义问题key列表
    'custom_questions_answered': {},  # 自定义问题回答结果
    'is_processing': False,  # 防重复处理标记
    'state': 'active',  # 会话状态
}
```

---

## API端点

### 1. 启动面试

```bash
POST /api/ai-interview/session/
Content-Type: application/json

{
    "action": "start",
    "candidate_id": "CAND_001",
    "resume": {
        "name": "张三",
        "skills": ["Python", "Django"],
        "projects": [...],
        "custom_questions": {
            "driving_license": "您会开车吗？",
            "other_cert": "有其他证书吗？"
        }
    },
    "job_config": {
        "title": "高级Python工程师",
        "requirements": "需要有大规模系统经验"
    },
    "required_hard_fields": ["english_level", "cert_pmp"]
}
```

### 2. 提交回答

```bash
POST /api/ai-interview/session/
Content-Type: application/json

{
    "action": "answer",
    "session_id": "uuid-string",
    "answer": "我的回答内容..."
}
```

### 3. 简历解析

```bash
POST /api/ai-interview/resume/parse/
Content-Type: multipart/form-data

file: 简历文件
```

---

## 答案质量验证

### 验证规则

```python
def validate_answer_quality(question, answer, round_type):
    issues = []

    # 1. 回答过短检测
    if len(answer.strip()) < 5:
        issues.append('回答过短')

    # 2. 第一人称检测
    if not any(indicator in answer for indicator in ['我', '本人', '我自己']):
        issues.append('缺少第一人称')

    # 3. 典型表述检测
    typical_patterns = ['负责', '参与', '主导', '完成', '实现', '开发', '设计']
    if sum(1 for p in typical_patterns if p in answer) < 2:
        issues.append('缺少典型表述')

    # 4. 逻辑性检测
    if len(answer) > 20 and answer.count('。') < 2:
        issues.append('长回答逻辑性存疑')

    is_valid = len(issues) == 0 or confidence > 0.5
    return {'valid': is_valid, 'issues': issues, 'confidence': confidence}
```

### 无效答案处理策略

1. **回答过短**: 重新表述问题
2. **连续2次无效**: 跳过该维度
3. **超时120秒+10秒等待**: 结束会话

---

## 缓存方案

**当前使用**: LocMemCache (Django内置)

**优势**: 无需额外安装服务，适合开发环境

**配置**:
```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}
```

---

## 模型配置

### 对话生成模型

- **当前使用**: `qwen-plus`
- **配置位置**: `.env` 中的 `QWEN_MODEL`

### 嵌入模型

- **模型**: `text-embedding-v4`
- **用途**: 语义相似度计算
- **配置位置**: `.env` 中的 `QWEN_EMBEDDING_MODEL`

---

## 错误处理

### 1. 防重复处理

使用 `is_processing` 标记防止并发请求：

```python
if session_data.get('is_processing', False):
    return {'error': '请求正在处理中，请稍候'}
```

### 2. 会话超时

```python
def is_session_timeout(self) -> bool:
    elapsed = time.time() - session_data.get('last_question_time', 0)
    base_timeout = getattr(settings, 'SESSION_TIMEOUT', 120)
    return elapsed > (base_timeout + self.WAIT_TIMEOUT_SECONDS)
```

---

## 提示词配置

**位置**: `ai_interview/services/prompts.py`

### 硬性字段提示词

```python
HARD_FIELD_PROMPT = """请根据以下信息生成一个面试问题来验证候选人的硬性资质。

候选人简历关键信息：
{resume_summary}

缺失的必问硬性字段：
{missing_fields}

请直接输出一个自然、深入的问题。"""
```

### 自定义问题处理

自定义问题直接从 `custom_questions` 字典中获取，不经过AI生成，确保原样提问。

---

## 更新日志

### 2026-05-15

1. **修复重复提问问题**: 添加 `is_processing` 防重复处理机制
2. **优化自定义问题处理**: 自定义问题全部在最后一轮处理，不占用独立轮次
3. **添加硬性字段分组**: 多个硬性字段统一在第一轮处理
4. **完善答案验证**: 添加更详细的验证规则和错误处理