import os
import json
import re
from typing import Dict, Any, Optional
from django.conf import settings
from .qwen_service import QwenService
from .prompts import get_prompt
from .token_utils import TokenRecorder


class ResumeParser:
    SUPPORTED_EXTENSIONS = ['.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.txt']
    
    @classmethod
    def parse_resume(cls, file_path: str, file_name: str) -> Dict[str, Any]:
        """解析简历文件，返回结构化JSON"""
        ext = os.path.splitext(file_name.lower())[1]
        
        if ext not in cls.SUPPORTED_EXTENSIONS:
            return {'error': f'不支持的文件格式: {ext}', 'supported_formats': cls.SUPPORTED_EXTENSIONS}
        
        try:
            text_content = cls._extract_text(file_path, ext)
            
            if not text_content or text_content.strip() == "":
                if ext == '.pdf':
                    return {'error': '无法提取PDF文本内容，请确认PDF不是纯扫描件，或安装OCR环境后重试', 'debug_info': {
                        'file_name': file_name,
                        'file_extension': ext,
                        'file_size': os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                        'extraction_error': 'PDF文本提取为空'
                    }}
                if '文档内容为空或无法提取文本' in text_content:
                    return {'error': '无法提取文件内容，请确保文件不为空', 'debug_info': {
                        'file_name': file_name,
                        'file_extension': ext,
                        'file_size': os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                        'extraction_error': text_content
                    }}
                return {'error': '无法提取文件内容，请确保文件不为空', 'debug_info': {
                    'file_name': file_name,
                    'file_extension': ext,
                    'file_size': os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                    'extracted_text': text_content[:100] if text_content else '空'
                }}
            
            parsed_result = cls._parse_with_ai(text_content)
            if 'error' not in parsed_result:
                parsed_result = cls._force_basic_contact_fields(parsed_result, text_content)
            return parsed_result
            
        except Exception as e:
            import traceback
            return {'error': f'解析失败: {str(e)}', 'debug_info': {
                'file_name': file_name,
                'file_extension': ext,
                'traceback': traceback.format_exc()
            }}
    
    @classmethod
    def _extract_text(cls, file_path: str, extension: str) -> str:
        """根据文件类型选择不同提取方案"""
        if not os.path.exists(file_path):
            return ""
        
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return ""
        
        strategies = {
            '.txt': cls._extract_txt,
            '.pdf': cls._extract_pdf_text,      # 多方案级联
            '.docx': cls._extract_docx_text,
            '.doc': cls._extract_doc_fallback,
            '.jpg': cls._extract_image_text,    # OCR识别
            '.jpeg': cls._extract_image_text,
            '.png': cls._extract_image_text,
        }
        return strategies.get(extension, lambda x: "")(file_path)
    
    @classmethod
    def _extract_txt(cls, file_path: str) -> str:
        """提取TXT文件文本"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception:
            return ""
    
    @classmethod
    def _extract_pdf_text(cls, file_path: str) -> str:
        """提取PDF文件文本"""
        extractors = [
            cls._extract_pdf_text_with_pdfplumber,
            cls._extract_pdf_text_with_pypdfium,
            cls._extract_pdf_text_fallback,
            cls._extract_pdf_text_with_ocr,
        ]

        for extractor in extractors:
            text = extractor(file_path)
            if text and text.strip():
                return text.strip()
        return ""

    @classmethod
    def _extract_pdf_text_with_pdfplumber(cls, file_path: str) -> str:
        """使用pdfplumber提取PDF文本"""
        try:
            import pdfplumber
            text = ""
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n\n"
            return text.strip()
        except Exception:
            return ""

    @classmethod
    def _extract_pdf_text_with_pypdfium(cls, file_path: str) -> str:
        """使用pypdfium2提取PDF文本"""
        try:
            import pypdfium2 as pdfium

            text_parts = []
            pdf = pdfium.PdfDocument(file_path)
            try:
                for page_index in range(len(pdf)):
                    page = pdf[page_index]
                    try:
                        text_page = page.get_textpage()
                        try:
                            page_text = text_page.get_text_range()
                            if page_text:
                                text_parts.append(page_text)
                        finally:
                            text_page.close()
                    finally:
                        page.close()
            finally:
                pdf.close()

            return "\n\n".join(text_parts).strip()
        except Exception:
            return ""
    
    @classmethod
    def _extract_pdf_text_fallback(cls, file_path: str) -> str:
        """PDF解析备用方案"""
        try:
            import subprocess
            result = subprocess.run(
                ['pdftotext', file_path, '-'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return ""

    @classmethod
    def _extract_pdf_text_with_ocr(cls, file_path: str) -> str:
        """将PDF页面渲染为图片后使用OCR提取文本"""
        try:
            import pypdfium2 as pdfium
            import pytesseract

            text_parts = []
            pdf = pdfium.PdfDocument(file_path)
            try:
                for page_index in range(len(pdf)):
                    page = pdf[page_index]
                    try:
                        bitmap = page.render(scale=2)
                        image = bitmap.to_pil()
                        page_text = pytesseract.image_to_string(image, lang='chi_sim+eng')
                        if page_text:
                            text_parts.append(page_text)
                    finally:
                        page.close()
            finally:
                pdf.close()

            return "\n\n".join(text_parts).strip()
        except Exception:
            return ""
    
    @classmethod
    def _extract_docx_text(cls, file_path: str) -> str:
        """提取DOC/DOCX文件文本"""
        try:
            from docx import Document
            
            if not os.path.exists(file_path):
                return f"文件不存在: {file_path}"
            
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return "文件为空"
            
            doc = Document(file_path)
            text_parts = []

            for para in doc.paragraphs:
                if para.text and para.text.strip():
                    text_parts.append(para.text.strip())

            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells if cell.text and cell.text.strip()]
                    if cells:
                        text_parts.append(" ".join(cells))

            for section in doc.sections:
                for container in [section.header, section.footer]:
                    for para in container.paragraphs:
                        if para.text and para.text.strip():
                            text_parts.append(para.text.strip())
                    for table in container.tables:
                        for row in table.rows:
                            cells = [cell.text.strip() for cell in row.cells if cell.text and cell.text.strip()]
                            if cells:
                                text_parts.append(" ".join(cells))

            text = "\n".join(text_parts)
            
            if text.strip():
                return text.strip()
            
            return "文档内容为空或无法提取文本"
            
        except ImportError:
            return "python-docx库未安装，请安装: pip install python-docx"
        except Exception as e:
            return f"Word文档解析错误: {str(e)}"
    
    @classmethod
    def _extract_doc_fallback(cls, file_path: str) -> str:
        """DOC格式文件解析备用方案"""
        try:
            import subprocess
            result = subprocess.run(
                ['antiword', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        
        try:
            import subprocess
            result = subprocess.run(
                ['catdoc', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        
        return "DOC格式文件解析失败，请尝试转换为DOCX格式或使用其他工具"
    
    @classmethod
    def _extract_image_text(cls, file_path: str) -> str:
        """使用OCR提取图片文本"""
        try:
            from PIL import Image
            import pytesseract
            
            custom_config = r'--oem 3 --psm 6'
            img = Image.open(file_path)
            text = pytesseract.image_to_string(img, config=custom_config, lang='chi_sim')
            return text.strip()
        except ImportError:
            return cls._extract_image_text_fallback(file_path)
        except Exception as e:
            return cls._extract_image_text_fallback(file_path)
    
    @classmethod
    def _extract_image_text_fallback(cls, file_path: str) -> str:
        """图片OCR备用方案"""
        try:
            import subprocess
            result = subprocess.run(
                ['tesseract', file_path, 'stdout', '-l', 'chi_sim'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return ""
    
    @classmethod
    def _parse_with_ai(cls, text_content: str) -> Dict[str, Any]:
        """调用Qwen大模型解析简历文本"""
        api_key = QwenService.get_api_key()
        if not api_key:
            return {'error': '未配置API密钥，请检查.env文件中的DASHSCOPE_API_KEY'}
        
        try:
            system_prompt = cls._resume_parser_system_prompt()
            user_prompt = cls._resume_parser_user_prompt(text_content)
            
            result = QwenService.generate_question(
                system_prompt=system_prompt,
                user_message=user_prompt,
                temperature=0.1,
                max_tokens=4000,
                use_advanced_model=False
            )
            
            try:
                parsed_json = cls._extract_json_from_response(result)
                parsed_result = cls._enhance_result_from_text(parsed_json, text_content)
                TokenRecorder.record_resume_parsing(system_prompt + user_prompt, result or '', QwenService.get_text_model())
                return parsed_result
            except json.JSONDecodeError:
                TokenRecorder.record_resume_parsing(system_prompt + user_prompt, result or '', QwenService.get_text_model())
                return cls._parse_fallback(text_content)
        
        except Exception as e:
            return {'error': f'AI解析错误: {str(e)}'}
    
    @classmethod
    def _resume_parser_system_prompt(cls) -> str:
        return """你是专业的中文简历信息抽取助手。你的任务是从简历原文中抽取信息，并只返回合法 JSON。

必须严格返回下面这个固定结构，不能新增字段，不能输出 Markdown，不能解释：
{
  "name": "",
  "phone": "",
  "email": "",
  "age": "",
  "gender": "",
  "location": "",
  "objective": "",
  "highest_education": "",
  "work_years": "",
  "skills": [],
  "certificates": [],
  "summary": "",
  "education": [
    {
      "school": "",
      "degree": "",
      "major": "",
      "start_date": "",
      "end_date": "",
      "description": ""
    }
  ],
  "experience": [
    {
      "company": "",
      "position": "",
      "start_date": "",
      "end_date": "",
      "description": ""
    }
  ],
  "internships": [
    {
      "company": "",
      "position": "",
      "start_date": "",
      "end_date": "",
      "description": ""
    }
  ],
  "projects": [
    {
      "name": "",
      "role": "",
      "start_date": "",
      "end_date": "",
      "description": "",
      "technologies": []
    }
  ],
  "awards": [],
  "languages": [],
  "hobbies": [],
  "expected_salary": "",
  "work_type": ""
}

抽取规则：
1. 只抽取原文真实出现的信息，不要猜测、不要补编。
2. 没提取到的字符串字段填空字符串，数组字段填空数组。
3. 教育背景必须尽量包含学校、学历、专业、时间；不要只返回“教育经历/教育背景”这种标题。
4. 项目经验必须一个项目一个对象，尽量保留项目名称、项目时间、角色、项目内容/职责/成果、技术栈；不要只返回项目标题。
5. 证书资质只放证书、资格、认证、等级考试，不要混入个人简介、教育、项目、工作内容。
6. 个人简介只放自我评价、职业概述、个人优势这类总结性内容，不要混入教育、工作、项目、证书明细。
7. 如果某段信息无法确定属于哪个字段，放到对应经历的 description 中，不要丢失简历里的有效内容。"""

    @classmethod
    def _resume_parser_user_prompt(cls, text_content: str) -> str:
        return f"""请把下面简历原文解析成固定 JSON。

特别注意：
- 教育背景不要只提取标题，要提取学校、学历、专业、时间、原文描述。
- 项目经验不要只提取标题，要把每个项目的内容、职责、成果、技术栈都放到对应项目对象里。
- 没提取到就返回空字符串或空数组，由前端显示“未提取到”。

简历原文：
{text_content}
"""

    @classmethod
    def _parse_fallback(cls, text_content: str) -> Dict[str, Any]:
        """AI解析失败时的规则引擎备用方案"""
        result = {
            'name': '', 'phone': '', 'email': '',
            'education': [], 'experience': [], 'projects': [],
            'skills': [], 'certificates': [], 'summary': text_content[:500],
        }
        
        if not text_content:
            return cls._normalize_result(result)
        
        sections = cls._split_resume_sections(text_content)  # 按标题分块
        
        result.update(cls._extract_basic_info(text_content))
        result['education'] = cls._extract_education(sections)
        result['experience'] = cls._extract_experience(sections.get('experience', ''))
        result['projects'] = cls._extract_projects(sections.get('projects', ''))
        result['skills'] = cls._extract_list_items(sections.get('skills', ''))
        
        return cls._normalize_result(result)

    @classmethod
    def _force_basic_contact_fields(cls, parsed_result: Dict[str, Any], text_content: str) -> Dict[str, Any]:
        """姓名、电话、邮箱用强规则最终兜底，其他字段保持 AI 解析结果不变。"""
        result = cls._normalize_result(parsed_result)
        basic_info = cls._extract_basic_info(text_content or '')

        for field in ['name', 'phone', 'email']:
            current = str(result.get(field) or '').strip()
            forced = str(basic_info.get(field) or '').strip()
            if forced and cls._should_replace_basic_field(field, current):
                result[field] = forced

        return result

    @classmethod
    def _should_replace_basic_field(cls, field: str, current: str) -> bool:
        if not current:
            return True
        if current in {'未提取到', '未识别', '无', '暂无', 'N/A', 'na', 'null', 'None'}:
            return True
        if cls._looks_like_section_or_resume_title(current):
            return True
        if field == 'phone':
            return not cls._is_valid_phone(current)
        if field == 'email':
            return not cls._is_valid_email(current)
        if field == 'name':
            return not cls._is_valid_candidate_name(current)
        return False

    @classmethod
    def _extract_json_from_response(cls, response: str) -> Dict[str, Any]:
        """从AI响应中提取JSON对象"""
        if not response:
            raise json.JSONDecodeError("empty response", "", 0)

        cleaned = response.strip()
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*```$', '', cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start != -1 and end != -1 and end > start:
                return json.loads(cleaned[start:end + 1])
            raise

    @classmethod
    def _merge_results(cls, primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
        """用规则解析结果补齐AI解析中的空字段"""
        merged = dict(primary)
        for key, fallback_value in fallback.items():
            current = merged.get(key)
            if current in (None, '', [], {}):
                merged[key] = fallback_value
            elif key == 'projects' and fallback_value:
                merged[key] = cls._merge_project_details(current, fallback_value)
            elif key == 'certificates':
                merged[key] = cls._merge_certificate_lists(current, fallback_value)
            elif key == 'summary' and len(str(current).strip()) < 20 and fallback_value:
                merged[key] = fallback_value
        return cls._normalize_result(merged)

    @classmethod
    def _merge_project_details(cls, primary_projects: Any, fallback_projects: Any) -> list:
        """AI 有时只返回项目标题，这里用规则解析的内容补齐描述、角色、时间和技术栈。"""
        primary = cls._normalize_projects(primary_projects)
        fallback = cls._normalize_projects(fallback_projects)
        if not primary:
            return fallback

        def score_match(project: dict, candidate: dict, index: int, candidate_index: int) -> int:
            name = (project.get('name') or '').strip()
            candidate_name = (candidate.get('name') or '').strip()
            if name and candidate_name and (name in candidate_name or candidate_name in name):
                return 3
            if index == candidate_index:
                return 2
            return 0

        merged = []
        used_fallback = set()
        for index, project in enumerate(primary):
            best_index = None
            best_score = 0
            for candidate_index, candidate in enumerate(fallback):
                if candidate_index in used_fallback:
                    continue
                score = score_match(project, candidate, index, candidate_index)
                if score > best_score:
                    best_score = score
                    best_index = candidate_index

            completed = dict(project)
            if best_index is not None:
                used_fallback.add(best_index)
                candidate = fallback[best_index]
                for field in ['description', 'role', 'start_date', 'end_date']:
                    if not completed.get(field) and candidate.get(field):
                        completed[field] = candidate[field]
                if not completed.get('technologies') and candidate.get('technologies'):
                    completed['technologies'] = candidate['technologies']
                if not completed.get('name') and candidate.get('name'):
                    completed['name'] = candidate['name']
            merged.append(completed)

        for candidate_index, candidate in enumerate(fallback):
            if candidate_index not in used_fallback:
                merged.append(candidate)
        return merged

    @classmethod
    def _merge_certificate_lists(cls, primary_certificates: Any, fallback_certificates: Any) -> list:
        merged = []
        for item in cls._normalize_string_list(primary_certificates) + cls._normalize_string_list(fallback_certificates):
            item = cls._clean_certificate_item(item)
            if item and cls._looks_like_certificate_item(item) and item not in merged:
                merged.append(item)
        return merged

    @classmethod
    def _split_resume_sections_v2(cls, text: str) -> Dict[str, str]:
        section_aliases = {
            'summary': ['个人简介', '自我介绍', '自我评价', '个人评价', '个人总结', '职业总结', '职业概述', '简介'],
            'education': ['教育经历', '教育背景', '教育情况', '学历背景', '学习经历', '毕业院校', '教育'],
            'experience': ['工作经历', '工作经验', '工作履历', '职业经历', '任职经历', '工作概况'],
            'internships': ['实习经历', '实习经验', '见习经历', '实习'],
            'projects': ['项目经历', '项目经验', '项目实践', '项目介绍', '项目背景', '项目概述'],
            'skills': ['专业技能', '技能清单', '技术技能', '职业技能', '核心技能', '技能特长', '技术栈', '技能'],
            'certificates': ['证书资质', '证书与资质', '资格证书', '资质证书', '职业资格', '专业证书', '认证证书', '证书', '认证'],
            'awards': ['获奖情况', '荣誉奖项', '所获荣誉', '获奖经历', '荣誉', '奖项'],
            'languages': ['语言能力', '语言水平', '外语能力', '英语水平', '英语'],
            'hobbies': ['兴趣爱好', '个人爱好', '爱好'],
        }
        title_to_key = {title: key for key, titles in section_aliases.items() for title in titles}
        title_pattern = '|'.join(sorted((re.escape(title) for title in title_to_key), key=len, reverse=True))
        sections = {'basic': []}
        current = 'basic'

        for raw_line in re.split(r'[\r\n]+', text or ''):
            line = raw_line.strip()
            if not line:
                continue
            normalized = re.sub(r'^[\s\-*•●▪◆■\d.、()（）]+', '', line).strip()
            normalized = re.sub(r'[：:]\s*$', '', normalized).strip()
            if current == 'projects' and re.match(r'^(项目名称|项目时间|担任角色|项目角色|项目描述|开发环境|主要成果|技术栈|名称|时间|角色|职责|描述|技术|成果)\s*[：:]', normalized):
                sections.setdefault(current, []).append(line)
                continue
            if normalized in title_to_key:
                current = title_to_key[normalized]
                sections.setdefault(current, [])
                continue
            inline = re.match(rf'^({title_pattern})\s*[：:]\s*(.*)$', normalized)
            if inline:
                current = title_to_key[inline.group(1)]
                sections.setdefault(current, [])
                if inline.group(2).strip():
                    sections[current].append(inline.group(2).strip())
                continue
            prefix = re.match(rf'^({title_pattern})(?:\s+|$)(.*)$', normalized)
            if prefix:
                current = title_to_key[prefix.group(1)]
                sections.setdefault(current, [])
                if prefix.group(2).strip():
                    sections[current].append(prefix.group(2).strip())
                continue
            sections.setdefault(current, []).append(line)

        return {key: '\n'.join(value).strip() for key, value in sections.items()}

    @classmethod
    def _clean_item_line_v2(cls, line: str) -> str:
        return re.sub(r'^[\s\-*•●▪◆■、()（）]+', '', str(line or '')).strip()

    @classmethod
    def _split_date_range_v2(cls, text: str) -> tuple:
        match = re.search(r'((?:19|20)\d{2}(?:[./年-]\d{1,2}月?)?)\s*(?:-|~|—|–|至|到)\s*((?:19|20)\d{2}(?:[./年-]\d{1,2}月?)?|至今|现在|今)', text or '')
        return (match.group(1).strip(), match.group(2).strip()) if match else ('', '')

    @classmethod
    def _extract_summary_v2(cls, sections: Dict[str, str], text: str) -> str:
        summary = sections.get('summary', '').strip()
        if not summary:
            match = re.search(r'(?:个人简介|自我介绍|自我评价|个人评价|职业概述)\s*[：:]\s*([\s\S]{10,600}?)(?=\n\s*(?:教育经历|教育背景|工作经历|工作经验|项目经历|项目经验|专业技能|技能|证书|资格证书|获奖|语言能力|$))', text or '')
            summary = match.group(1).strip() if match else ''
        lines = []
        for line in re.split(r'[\r\n]+', summary):
            cleaned = cls._clean_item_line_v2(line)
            if cleaned and not cls._looks_like_section_or_resume_title(cleaned):
                lines.append(cleaned)
        return '\n'.join(lines)[:500].strip()

    @classmethod
    def _looks_like_section_or_resume_title(cls, text: str) -> bool:
        if not text:
            return True
        if re.fullmatch(r'(个人)?简历|求职简历|我的简历|Resume|CV', text, flags=re.IGNORECASE):
            return True
        return bool(re.search(r'^(教育经历|教育背景|工作经历|工作经验|项目经历|项目经验|专业技能|技能|证书资质|证书|获奖|语言能力|个人信息|基本信息)\s*[：:]?$', text))

    @classmethod
    def _extract_education_v2(cls, text: str) -> list:
        items = []
        for line in [cls._clean_item_line_v2(l) for l in re.split(r'[\r\n]+', text or '') if cls._clean_item_line_v2(l)]:
            school = re.search(r'([\u4e00-\u9fa5A-Za-z0-9·（）()]+(?:大学|学院|学校|中学|职业技术学院|师范|研究院))', line)
            degree = re.search(r'(博士|硕士|研究生|本科|大专|专科|高中|中专|MBA|EMBA)', line)
            if not school and not degree:
                continue
            major = re.search(r'([\u4e00-\u9fa5A-Za-z0-9（）()]+(?:专业|方向|工程|科学|管理|设计|技术|教育|金融|会计|营销|英语|医学|法学))', line)
            start_date, end_date = cls._split_date_range_v2(line)
            items.append({
                'school': school.group(1).strip() if school else '',
                'degree': degree.group(1).strip() if degree else '',
                'major': major.group(1).replace('专业', '').strip() if major else '',
                'start_date': start_date,
                'end_date': end_date,
                'description': line,
            })
        return items

    @classmethod
    def _extract_experience_v2(cls, text: str) -> list:
        lines = [cls._clean_item_line_v2(l) for l in re.split(r'[\r\n]+', text or '') if cls._clean_item_line_v2(l)]
        items = []
        current = None
        company_pattern = r'([\u4e00-\u9fa5A-Za-z0-9·（）()]+(?:公司|集团|科技|网络|软件|信息|咨询|银行|医院|学校|事务所|工作室|中心|研究院))'

        def finish():
            if current and any(current.get(k) for k in ['company', 'position', 'description']):
                items.append(current.copy())

        for line in lines:
            start_date, end_date = cls._split_date_range_v2(line)
            company = re.search(company_pattern, line)
            has_new_item = bool(start_date or company) and not re.match(r'^(负责|参与|主导|完成|协助|职责|工作内容)', line)
            if has_new_item:
                finish()
                company_text = company.group(1).strip() if company else ''
                rest = line.replace(company_text, '').strip(' -—|，,')
                if start_date:
                    rest = re.sub(r'((?:19|20)\d{2}.*?(?:至今|现在|今|(?:19|20)\d{2}(?:[./年-]\d{1,2}月?)?))', '', rest, count=1).strip(' -—|，,')
                current = {'company': company_text, 'position': rest, 'start_date': start_date, 'end_date': end_date, 'description': ''}
            elif current:
                current['description'] = (current.get('description', '') + '\n' + line).strip()
            else:
                current = {'company': '', 'position': '', 'start_date': start_date, 'end_date': end_date, 'description': line}
        finish()
        return items

    @classmethod
    def _extract_projects_v2(cls, text: str) -> list:
        lines = [cls._clean_item_line_v2(l) for l in re.split(r'[\r\n]+', text or '') if cls._clean_item_line_v2(l)]
        projects = []
        current = None

        def finish():
            if current and any(current.get(k) for k in ['name', 'role', 'description', 'technologies']):
                projects.append(current.copy())

        for line in lines:
            field = re.match(r'^(项目名称|项目时间|担任角色|项目角色|项目描述|开发环境|主要成果|技术栈|名称|时间|角色|职责|描述|技术|成果|项目)\s*[：:]\s*(.+)$', line)
            start_date, end_date = cls._split_date_range_v2(line)
            if field:
                key, value = field.group(1), field.group(2).strip()
                if key in {'项目名称', '项目', '名称'}:
                    finish()
                    current = {'name': value, 'role': '', 'description': '', 'technologies': [], 'start_date': '', 'end_date': ''}
                else:
                    if current is None:
                        current = {'name': '', 'role': '', 'description': '', 'technologies': [], 'start_date': '', 'end_date': ''}
                    if key in {'项目时间', '时间'}:
                        current['start_date'], current['end_date'] = cls._split_date_range_v2(value)
                    elif key in {'担任角色', '项目角色', '角色'}:
                        current['role'] = value
                    elif key in {'技术栈', '技术', '开发环境'}:
                        current['technologies'] = [v.strip() for v in re.split(r'[,，、/|；;]', value) if v.strip()]
                    else:
                        current['description'] = (current.get('description', '') + '\n' + value).strip()
            elif start_date and re.search(r'(项目|系统|平台|小程序|APP|应用|网站|管理|服务)', line):
                finish()
                name = re.sub(r'((?:19|20)\d{2}.*?(?:至今|现在|今|(?:19|20)\d{2}(?:[./年-]\d{1,2}月?)?))', '', line, count=1).strip(' -—|，,')
                current = {'name': name, 'role': '', 'description': '', 'technologies': [], 'start_date': start_date, 'end_date': end_date}
            else:
                if current is None:
                    if re.search(r'(项目|系统|平台|小程序|APP|应用|网站|管理|服务|平台)', line):
                        current = {'name': line, 'role': '', 'description': '', 'technologies': [], 'start_date': '', 'end_date': ''}
                    else:
                        current = {'name': '', 'role': '', 'description': '', 'technologies': [], 'start_date': '', 'end_date': ''}
                        current['description'] = line
                else:
                    if re.search(r'(项目|系统|平台|小程序|APP|应用|网站|管理|服务|平台)', line) and not current.get('name'):
                        current['name'] = line
                    else:
                        current['description'] = (current.get('description', '') + '\n' + line).strip()
        finish()
        for item in projects:
            if not item.get('technologies'):
                item['technologies'] = cls._extract_technologies(item.get('description', ''))
        return projects

    @classmethod
    def _extract_list_items_v2(cls, text: str) -> list:
        items = []
        for line in re.split(r'[\r\n；;]+', text or ''):
            line = cls._clean_item_line_v2(line)
            if not line:
                continue
            if re.match(r'^[^：:]{2,12}[：:]', line):
                line = re.split(r'[：:]', line, maxsplit=1)[1].strip()
            for value in re.split(r'[,，、/|]', line):
                value = value.strip()
                if value and value not in items:
                    items.append(value)
        return items

    @classmethod
    def _extract_certificates_v2(cls, text: str) -> list:
        items = cls._extract_list_items_v2(text)
        
        known_certificates = [
            'CET-4', 'CET-6', '英语四级', '英语六级', '大学英语四级', '大学英语六级',
            '计算机一级', '计算机二级', '计算机三级', '计算机四级',
            '软考', '系统架构师', '软件设计师', '数据库系统工程师',
            'PMP', 'CPA', 'CFA', 'ACCA', 'FRM',
            '教师资格证', '法律职业资格', '证券从业资格', '基金从业资格',
            'AWS认证', 'Azure认证', 'Google认证', '华为认证', '思科认证', 'Oracle认证',
        ]
        
        for cert in known_certificates:
            pattern = re.escape(cert)
            if re.search(pattern, text or '', flags=re.IGNORECASE):
                if cert not in items:
                    items.append(cert)
        
        known_patterns = [
            r'CET[-\s]?[46]', 
            r'(?:大学)?英语[四六]级',
            r'计算机[一二三四]级', 
            r'软考[^\s，,；;、]*', 
            r'PMP|CPA|CFA|ACCA|FRM',
            r'教师资格证?', 
            r'法律职业资格', 
            r'证券从业资格', 
            r'基金从业资格',
            r'AWS[^\s，,；;、]*认证', 
            r'Azure[^\s，,；;、]*认证', 
            r'华为[^\s，,；;、]*认证',
            r'思科[^\s，,；;、]*认证',
            r'Oracle[^\s，,；;、]*认证',
        ]
        for pattern in known_patterns:
            for match in re.findall(pattern, text or '', flags=re.IGNORECASE):
                value = match if isinstance(match, str) else ''.join(match)
                value = value.strip()
                if value and value not in items and len(value) >= 2:
                    items.append(value)
        
        filtered_items = []
        for item in items:
            item = cls._clean_certificate_item(item)
            if item and cls._looks_like_certificate_item(item) and item not in filtered_items:
                filtered_items.append(item)
        
        return filtered_items

    @classmethod
    def _clean_certificate_item(cls, item: Any) -> str:
        text = str(item or '').strip()
        if not text:
            return ''
        text = re.sub(r'^(证书资质|证书与资质|资格证书|资质证书|职业资格|专业证书|认证证书|证书|认证)\s*[：:]\s*', '', text).strip()
        if not text or len(text) < 2:
            return ''
        if cls._looks_like_section_or_resume_title(text):
            return ''
        exclude_keywords = ['个人简介', '自我介绍', '项目经历', '项目经验', '工作经历', '工作经验', '教育经历', '教育背景', '专业技能']
        if any(keyword in text for keyword in exclude_keywords):
            return ''
        if len(text) > 80:
            return ''
        return text

    @classmethod
    def _looks_like_certificate_item(cls, item: str) -> bool:
        return bool(re.search(
            r'(证|认证|资格|CET|英语[四六四六]级|计算机[一二三四]级|软考|PMP|CPA|CFA|ACCA|FRM|普通话|二甲|雅思|托福|IELTS|TOEFL|AWS|Azure|Google|华为|思科|Oracle)',
            item,
            flags=re.IGNORECASE
        ))

    @classmethod
    def _enhance_result_from_text(cls, result: Dict[str, Any], text: str) -> Dict[str, Any]:
        result = cls._normalize_result(result)
        sections = cls._split_resume_sections_v2(text or '')
        if not result.get('summary'):
            result['summary'] = cls._extract_summary_v2(sections, text)
        if not result.get('education'):
            result['education'] = cls._extract_education_v2(sections.get('education', '') or text)
        if not result.get('experience'):
            result['experience'] = cls._extract_experience_v2(sections.get('experience', '') or text)
        if not result.get('projects'):
            result['projects'] = cls._extract_projects_v2(sections.get('projects', '') or text)
        if not result.get('certificates'):
            result['certificates'] = cls._extract_certificates_v2(sections.get('certificates', '') or text)
        else:
            result['certificates'] = cls._merge_certificate_lists(result.get('certificates'), [])
        if result.get('summary'):
            summary_lines = [
                cls._clean_item_line_v2(line)
                for line in re.split(r'[\r\n]+', str(result.get('summary') or ''))
            ]
            result['summary'] = '\n'.join(
                line for line in summary_lines
                if line and not cls._looks_like_section_or_resume_title(line)
            )[:500].strip()
        return cls._normalize_result(result)

    @classmethod
    def _split_resume_sections(cls, text: str) -> Dict[str, str]:
        """按简历常见标题拆分文本区块"""
        section_aliases = {
            'summary': ['个人简介', '自我介绍', '自我评价', '个人评价', '个人总结', '职业总结', '自我简介', '职业概述', '简介'],
            'education': ['教育经历', '教育背景', '教育情况', '学历背景', '学习经历', '求学经历', '教育概况', '学历', '本科', '硕士', '博士', '大专', '毕业院校'],
            'experience': ['工作经历', '工作经验', '工作履历', '职业经历', '从业经历', '工作概况', '工作', '职位', '公司'],
            'internships': ['实习经历', '实习经验', '见习经历', '实习'],
            'projects': ['项目经历', '项目经验', '项目实践', '项目介绍', '项目背景', '项目概述', '项目'],
            'skills': ['专业技能', '技能', '技能清单', '技术技能', '职业技能', '核心技能', '技能特长', '技术栈'],
            'certificates': ['证书', '证书与资质', '资格证书', '资质证书', '职业资格', '专业证书', '认证'],
            'awards': ['获奖情况', '荣誉奖项', '所获荣誉', '奖项', '荣誉证书', '获奖经历', '荣誉'],
            'languages': ['语言能力', '语言水平', '外语能力', '英语水平', '英语'],
            'hobbies': ['兴趣爱好', '爱好', '个人爱好'],
        }
        title_to_key = {title: key for key, titles in section_aliases.items() for title in titles}
        title_pattern = '|'.join(re.escape(title) for title in title_to_key)
        lines = [line.strip() for line in re.split(r'[\r\n]+', text) if line.strip()]
        sections = {'basic': []}
        current = 'basic'

        for line in lines:
            normalized = re.sub(r'^[\d\-\*•·\s]+', '', line).strip()
            normalized = re.sub(r'[：:]\s*$', '', normalized)
            
            if re.match(r'^(姓名|名字|电话|手机|邮箱|性别|年龄|所在地|现居地|居住地|求职意向|期望职位|期望薪资|应聘岗位|学历|专业)\s*[：:]', normalized):
                sections.setdefault('basic', []).append(normalized)
                continue
            
            inline_match = re.match(rf'^({title_pattern})[：:]\s*(.+)$', normalized)
            if inline_match:
                current = title_to_key[inline_match.group(1)]
                sections.setdefault(current, [])
                sections[current].append(inline_match.group(2).strip())
                continue
            
            contains_title = False
            for title in title_to_key:
                if title in normalized and len(normalized) > len(title) + 1:
                    idx = normalized.find(title)
                    if idx == 0 or normalized[idx-1] in (' ', '\t', '：', ':', '、'):
                        current = title_to_key[title]
                        remaining = normalized[idx+len(title):].strip()
                        if remaining.startswith((':', '：')):
                            remaining = remaining[1:].strip()
                        if remaining:
                            sections.setdefault(current, []).append(remaining)
                        else:
                            sections.setdefault(current, [])
                        contains_title = True
                        break
            
            if contains_title:
                continue
            
            search_match = re.search(rf'^({title_pattern})', normalized)
            if search_match:
                title_text = search_match.group(1)
                rest = normalized[len(title_text):].strip()
                if rest and not rest.startswith((':', '：')):
                    sections.setdefault(current, []).append(line)
                    continue
                current = title_to_key[title_text]
                sections.setdefault(current, [])
                continue
            
            sections.setdefault(current, []).append(line)

        return {key: '\n'.join(value) for key, value in sections.items()}

    @classmethod
    def _extract_basic_info(cls, text: str) -> Dict[str, Any]:
        """提取姓名、电话、邮箱、求职意向 - 严格正则匹配"""
        result = {'name': '', 'phone': '', 'email': '', 'objective': ''}
        text = cls._normalize_basic_text(text or '')
        
        # 电话号码匹配（支持多种格式：手机号、座机、带分隔符）
        phone_patterns = [
            r'(?:电话|手机|联系方式|联系电话|联系电话号码|Tel|Mobile|Phone)[ \t]*[：:]?[ \t]*((?:\+?86[- \t]?)?1[3-9]\d[\d \t-]{8,16})',
            r'(?:\+?86[-\s]?)?(?:1[3-9]\d{9})',                            # 手机号
            r'(?:\+?86[-\s]?)?(?:1[3-9]\d{2}[\s-]?\d{4}[\s-]?\d{4})',       # 带分隔符手机号
            r'(?:\+?86[-\s]?)?(?:0\d{2,3}[\s-]?)\d{7,8}',                  # 座机号
            r'(?:\+?86[-\s]?)?(?:0\d{2,3}[\s-]?)\d{3,4}[\s-]?\d{4}',       # 带分机座机号
        ]
        for pattern in phone_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                phone_source = match.group(1) if match.lastindex else match.group(0)
                phone = cls._clean_phone(phone_source)
                if phone:
                    result['phone'] = phone
                    break
        if not result['phone']:
            for candidate in re.findall(r'(?:\+?86[- \t]?)?1[3-9]\d(?:[\d \t-]{8,16})', text):
                phone = cls._clean_phone(candidate)
                if phone:
                    result['phone'] = phone
                    break
        
        # 邮箱匹配（支持多种格式）
        email_patterns = [
            r'(?:邮箱|电子邮箱|邮件|Email|E-mail|Mail)\s*[：:\s]*([a-zA-Z0-9._%+-]+\s*@\s*[a-zA-Z0-9.-]+\s*\.\s*[a-zA-Z]{2,})',
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',              # 标准邮箱
            r'[a-zA-Z0-9._%+-]+\s*@\s*[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',        # 带空格邮箱
            r'[a-zA-Z0-9._%+-]+\s*(?:[（(]\s*at\s*[）)]|\sat\s)\s*[a-zA-Z0-9.-]+\s*\.\s*[a-zA-Z]{2,}', # 文字at格式
        ]
        for pattern in email_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                email_source = match.group(1) if match.lastindex else match.group(0)
                email = cls._clean_email(email_source)
                if email:
                    result['email'] = email
                    break
        
        # 姓名匹配（严格匹配）
        name_patterns = [
            r'(?:姓名|名字|Name|name)[ \t]*[：:]?[ \t]*([\u4e00-\u9fa5·]{2,8}|[A-Za-z][A-Za-z \t]{1,40})',
            r'(?:姓\s*名|名\s*字)[ \t]*[：:]?[ \t]*([\u4e00-\u9fa5·]{2,8})',
            r'(?:候选人|应聘者)[ \t]*[：:]?[ \t]*([\u4e00-\u9fa5·]{2,8}|[A-Za-z][A-Za-z \t]{1,40})',
            r'^\s*([\u4e00-\u9fa5·]{2,4})\s*(?:先生|女士|小姐)?\s*$',
            r'^(?:个人简历|求职简历|简历|Resume|CV)[ \t]*\n[ \t]*([\u4e00-\u9fa5·]{2,4}|[A-Za-z][A-Za-z \t]{1,40})[ \t]*',
        ]
        for pattern in name_patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                name = cls._clean_name(match.group(1))
                if cls._is_valid_candidate_name(name):
                    result['name'] = name
                    break

        if not result['name']:
            result['name'] = cls._guess_name_from_top_lines(text)
        
        # 求职意向匹配
        objective_patterns = [
            r'(?:求职意向|应聘岗位|目标岗位|期望职位|意向岗位)\s*[：:]\s*([^\n\r，,；;]{2,80})',
            r'(?:求职意向|应聘岗位|目标岗位|期望职位|意向岗位)\s*([^\n\r，,；;]{2,80})',
        ]
        for pattern in objective_patterns:
            match = re.search(pattern, text)
            if match:
                result['objective'] = match.group(1).strip()
                break

        return result

    @classmethod
    def _normalize_basic_text(cls, text: str) -> str:
        full_width_digits = str.maketrans('０１２３４５６７８９', '0123456789')
        text = str(text or '').translate(full_width_digits)
        replacements = {
            '＠': '@',
            '．': '.',
            '﹒': '.',
            '。': '.',
            '（': '(',
            '）': ')',
            '－': '-',
            '—': '-',
            '–': '-',
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    @classmethod
    def _clean_phone(cls, value: str) -> str:
        digits = re.sub(r'\D', '', value or '')
        if digits.startswith('86') and len(digits) > 11:
            digits = digits[2:]
        if re.fullmatch(r'1[3-9]\d{9}', digits):
            return digits
        if re.fullmatch(r'0\d{9,11}', digits):
            return digits
        return ''

    @classmethod
    def _clean_email(cls, value: str) -> str:
        email = str(value or '').strip()
        email = re.sub(r'\s*(?:\(|（)?\s*at\s*(?:\)|）)?\s*', '@', email, flags=re.IGNORECASE)
        email = re.sub(r'\s*@\s*', '@', email)
        email = re.sub(r'\s*\.\s*', '.', email)
        email = re.sub(r'^(邮箱|电子邮箱|邮件|Email|E-mail|Mail)\s*[：:\s]*', '', email, flags=re.IGNORECASE)
        match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', email)
        return match.group(0) if match else ''

    @classmethod
    def _clean_name(cls, value: str) -> str:
        name = str(value or '').strip()
        name = re.sub(r'^(姓名|名字|候选人|应聘者|Name|name)\s*[：:\s]*', '', name, flags=re.IGNORECASE).strip()
        name = re.sub(r'\s*(先生|女士|小姐)$', '', name).strip()
        return name

    @classmethod
    def _is_valid_candidate_name(cls, name: str) -> bool:
        name = str(name or '').strip()
        if not name:
            return False
        bad_tokens = ['简历', '求职', '个人', '电话', '手机', '邮箱', '教育', '经历', '项目', '技能', '证书', '岗位', '应聘']
        if any(token in name for token in bad_tokens):
            return False
        return bool(
            re.fullmatch(r'[\u4e00-\u9fa5·]{2,8}', name)
            or re.fullmatch(r'[A-Za-z][A-Za-z \t]{1,40}', name)
        )

    @classmethod
    def _guess_name_from_top_lines(cls, text: str) -> str:
        lines = [cls._clean_item_line_v2(line) for line in re.split(r'[\r\n]+', text or '')]
        lines = [line for line in lines[:12] if line]
        for line in lines:
            if any(token in line for token in ['电话', '手机', '邮箱', '@', '求职', '岗位', '教育', '工作', '项目', '技能']):
                continue
            line = re.sub(r'\s+', ' ', line).strip()
            if cls._is_valid_candidate_name(line):
                return line
        return ''

    @classmethod
    def _extract_summary(cls, sections: Dict[str, str], text: str) -> str:
        summary = sections.get('summary', '').strip()
        if summary:
            return cls._clean_summary(summary)
        
        for pattern in [
            r'(?:个人简介|自我介绍|自我评价|个人评价|自我简介|职业概述)\s*[：:]\s*([\s\S]{20,500}?)(?:\n\s*(?:教育经历|教育背景|工作经历|工作经验|项目经历|项目经验|专业技能|技能|证书|获奖|语言|兴趣|姓名|电话|邮箱|年龄|性别|所在地)|$)',
            r'(?:个人简介|自我介绍|自我评价|个人评价|自我简介|职业概述)\s*[：:]\s*([^\n]{20,200})',
        ]:
            match = re.search(pattern, text)
            if match:
                return cls._clean_summary(match.group(1).strip())
        
        return ""
    
    @classmethod
    def _clean_summary(cls, summary: str) -> str:
        """清理个人简介内容，移除不属于简介的信息"""
        exclude_patterns = [
            r'(姓名|电话|手机|邮箱|年龄|性别|所在地|求职意向|期望职位|期望薪资|应聘岗位|学历|专业)\s*[：:]',
            r'^\d+\s*[-~至到]\s*\d+',
            r'(教育经历|教育背景|工作经历|工作经验|项目经历|项目经验|专业技能|技能|证书|获奖|语言|兴趣)',
        ]
        
        lines = summary.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            exclude = False
            for pattern in exclude_patterns:
                if re.search(pattern, line):
                    exclude = True
                    break
            
            if not exclude and len(line) >= 5:
                cleaned_lines.append(line)
        
        result = '\n'.join(cleaned_lines)[:500].strip()
        return result if len(result) >= 10 else ""

    @classmethod
    def _clean_item_line(cls, line: str) -> str:
        return re.sub(r'^[\-*•●▪\d.、\s]+', '', line).strip()

    @classmethod
    def _extract_list_items(cls, section_text: str) -> list:
        if not section_text:
            return []
        items = []
        for raw_line in re.split(r'[\n；;]+', section_text):
            line = cls._clean_item_line(raw_line)
            if not line:
                continue
            if '：' in line or ':' in line:
                _, value = re.split(r'[：:]', line, maxsplit=1)
                candidates = re.split(r'[,，、/|]', value)
            else:
                candidates = re.split(r'[,，、/|]', line)
            for candidate in candidates:
                value = candidate.strip()
                if value and value not in items:
                    items.append(value)
        return items

    @classmethod
    def _extract_education(cls, sections: Dict[str, str]) -> list:
        text = sections.get('education', '')
        if not text:
            return []
        items = []
        for line in re.split(r'\n+', text):
            line = cls._clean_item_line(line)
            if not line:
                continue
            date_match = re.search(r'((?:19|20)\d{2}(?:[./年-]\d{1,2}月?)?\s*[-~至到]\s*(?:(?:19|20)\d{2}(?:[./年-]\d{1,2}月?)?|至今|现在|今))', line)
            degree_match = re.search(r'(博士|硕士|研究生|本科|大专|专科|高中|中专)', line)
            major_match = re.search(r'([\u4e00-\u9fa5A-Za-z0-9]+(?:专业|方向))', line)
            school_match = re.search(r'([\u4e00-\u9fa5A-Za-z0-9·]+(?:大学|学院|学校|中学))', line)
            items.append({
                'school': school_match.group(1) if school_match else '',
                'degree': degree_match.group(1) if degree_match else '',
                'major': major_match.group(1).replace('专业', '') if major_match else '',
                'start_date': date_match.group(1).split('-')[0].strip() if date_match and '-' in date_match.group(1) else '',
                'end_date': date_match.group(1).split('-')[-1].strip() if date_match and '-' in date_match.group(1) else '',
                'description': line,
            })
        return items

    @classmethod
    def _extract_experience(cls, section_text: str) -> list:
        if not section_text:
            return []
        lines = [cls._clean_item_line(line) for line in section_text.splitlines() if cls._clean_item_line(line)]
        items = []
        current = None
        date_pattern = r'(?:19|20)\d{2}(?:年\d{1,2}月?|[./-]\d{1,2})?\s*[-~至到]\s*(?:(?:19|20)\d{2}(?:年\d{1,2}月?|[./-]\d{1,2})?|至今|现在|今)'

        for line in lines:
            if re.search(date_pattern, line):
                if current:
                    items.append(current)
                date_text = re.search(date_pattern, line).group(0)
                rest = line.replace(date_text, '').strip(' -—，,')
                parts = rest.split()
                current = {
                    'company': parts[-1] if len(parts) >= 2 else '',
                    'position': ' '.join(parts[:-1]) if len(parts) >= 2 else rest,
                    'start_date': re.split(r'[-~至到]', date_text)[0].strip(),
                    'end_date': re.split(r'[-~至到]', date_text)[-1].strip(),
                    'description': '',
                }
            elif current:
                current['description'] = (current['description'] + '\n' + line).strip()
            else:
                current = {'company': '', 'position': '', 'start_date': '', 'end_date': '', 'description': line}

        if current:
            items.append(current)
        return items

    @classmethod
    def _extract_projects(cls, section_text: str) -> list:
        if not section_text:
            return []
        lines = [cls._clean_item_line(line) for line in section_text.splitlines() if cls._clean_item_line(line)]
        projects = []
        current = None

        def finish_project():
            if current and any(current.get(key) for key in ['name', 'description', 'role', 'technologies']):
                projects.append(current.copy())

        for line in lines:
            field_match = re.match(r'(项目时间|时间|担任角色|项目角色|角色|项目描述|描述|技术栈|技术|主要成就|成果)[：:]\s*(.+)', line)
            inline_match = re.match(r'([^：:]{2,40})[：:]\s*(.+)', line)

            if field_match and current:
                key, value = field_match.group(1), field_match.group(2).strip()
                if key in ['项目时间', '时间']:
                    dates = re.split(r'[-~至到]', value)
                    current['start_date'] = dates[0].strip() if dates else ''
                    current['end_date'] = dates[-1].strip() if len(dates) > 1 else ''
                elif key in ['担任角色', '项目角色', '角色']:
                    current['role'] = value
                elif key in ['技术栈', '技术']:
                    current['technologies'] = [item.strip() for item in re.split(r'[,，、/|]', value) if item.strip()]
                else:
                    current['description'] = (current.get('description', '') + '\n' + value).strip()
            elif inline_match and not any(prefix in line for prefix in ['电话', '邮箱', '姓名']):
                finish_project()
                current = {
                    'name': inline_match.group(1).strip(),
                    'role': '',
                    'description': inline_match.group(2).strip(),
                    'technologies': [],
                    'start_date': '',
                    'end_date': '',
                }
            else:
                if current is None or re.search(r'(系统|平台|项目|应用|网站|小程序|服务)$', line):
                    finish_project()
                    current = {
                        'name': line,
                        'role': '',
                        'description': '',
                        'technologies': [],
                        'start_date': '',
                        'end_date': '',
                    }
                else:
                    current['description'] = (current.get('description', '') + '\n' + line).strip()

        finish_project()
        return projects

    @classmethod
    def _extract_languages(cls, section_text: str) -> list:
        languages = []
        for item in cls._extract_list_items(section_text):
            parts = re.split(r'[：:]', item, maxsplit=1)
            if len(parts) == 2:
                languages.append({'language': parts[0].strip(), 'level': parts[1].strip()})
            elif item:
                languages.append({'language': item, 'level': ''})
        return languages

    @classmethod
    def _canonicalize_result_keys(cls, result: Dict[str, Any]) -> Dict[str, Any]:
        aliases = {
            'education': ['educations', 'education_background', 'educationBackground', '教育背景', '教育经历'],
            'experience': ['work_experience', 'workExperience', 'work_experiences', '工作经历', '工作经验'],
            'internships': ['internship', 'internship_experience', '实习经历'],
            'projects': ['project_experience', 'projectExperience', 'project_experiences', '项目经验', '项目经历'],
            'certificates': ['certificate', 'certificate_qualifications', 'certifications', 'qualifications', '证书资质', '证书'],
            'summary': ['profile', 'personal_profile', 'personal_summary', 'self_evaluation', '个人简介', '自我评价'],
            'skills': ['skill', 'professional_skills', '专业技能'],
            'awards': ['honors', 'honor_awards', '荣誉奖项'],
            'languages': ['language', 'language_skills', '语言能力'],
            'objective': ['job_intention', 'career_objective', '求职意向'],
            'phone': ['mobile', 'telephone', '手机号', '电话'],
            'email': ['mail', '邮箱'],
        }
        normalized = dict(result)
        for target, source_keys in aliases.items():
            if normalized.get(target) in (None, '', [], {}):
                for source in source_keys:
                    if result.get(source) not in (None, '', [], {}):
                        normalized[target] = result.get(source)
                        break
        return normalized
    
    @classmethod
    def _normalize_result(cls, result: Dict[str, Any]) -> Dict[str, Any]:
        """标准化解析结果"""
        result = cls._canonicalize_result_keys(result or {})
        default_fields = {
            'name': '',
            'phone': '',
            'email': '',
            'age': '',
            'gender': '',
            'location': '',
            'objective': '',
            'education': [],
            'experience': [],
            'internships': [],
            'projects': [],
            'skills': [],
            'certificates': [],
            'awards': [],
            'languages': [],
            'summary': '',
            'hobbies': [],
            'expected_salary': '',
            'work_type': '',
        }
        
        for field in default_fields:
            if field not in result:
                result[field] = default_fields[field]
        
        result['education'] = cls._normalize_education(result['education'])
        result['experience'] = cls._normalize_experience(result['experience'])
        result['internships'] = cls._normalize_internships(result['internships'])
        result['projects'] = cls._normalize_projects(result['projects'])
        result['languages'] = cls._normalize_languages(result['languages'])
        result['skills'] = cls._normalize_string_list(result['skills'])
        clean_certificates = []
        for item in (cls._clean_certificate_item(v) for v in cls._normalize_string_list(result['certificates'])):
            if item and cls._looks_like_certificate_item(item) and item not in clean_certificates:
                clean_certificates.append(item)
        result['certificates'] = clean_certificates
        result['awards'] = cls._normalize_string_list(result['awards'])
        result['hobbies'] = cls._normalize_string_list(result['hobbies'])
        result['summary'] = cls._clean_summary_text(result.get('summary', ''))
        
        return result

    @classmethod
    def _clean_summary_text(cls, summary: Any) -> str:
        lines = []
        for line in re.split(r'[\r\n]+', str(summary or '')):
            cleaned = cls._clean_item_line_v2(line)
            if cleaned and not cls._looks_like_section_or_resume_title(cleaned):
                lines.append(cleaned)
        return '\n'.join(lines)[:500].strip()

    @classmethod
    def _normalize_string_list(cls, value: Any) -> list:
        if value in (None, '', [], {}):
            return []
        if isinstance(value, dict):
            value = list(value.values())
        if isinstance(value, str):
            value = re.split(r'[,，、/|；;\n]+', value)
        result = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    item = ' '.join(str(v).strip() for v in item.values() if str(v).strip())
                text = str(item).strip()
                if text and text not in result:
                    result.append(text)
        return result
    
    @classmethod
    def _normalize_education(cls, education: list) -> list:
        """标准化教育经历"""
        if isinstance(education, dict):
            education = [education]
        elif isinstance(education, str):
            education = [education]
        normalized = []
        for item in education:
            if isinstance(item, dict):
                normalized_item = {
                    'school': str(item.get('school', '')).strip(),
                    'degree': str(item.get('degree', '')).strip(),
                    'major': str(item.get('major', '')).strip(),
                    'start_date': str(item.get('start_date', '')).strip(),
                    'end_date': str(item.get('end_date', '')).strip(),
                    'description': str(item.get('description', '')).strip(),
                }
                if any(normalized_item.values()) and not cls._looks_like_section_or_resume_title(''.join(normalized_item.values())):
                    normalized.append(normalized_item)
            elif isinstance(item, str):
                text = item.strip()
                if text and not cls._looks_like_section_or_resume_title(text):
                    normalized.append({
                        'school': text,
                        'degree': '',
                        'major': '',
                        'start_date': '',
                        'end_date': '',
                        'description': '',
                    })
        return normalized
    
    @classmethod
    def _normalize_experience(cls, experience: list) -> list:
        """标准化工作经历"""
        if isinstance(experience, dict):
            experience = [experience]
        elif isinstance(experience, str):
            experience = [experience]
        normalized = []
        for item in experience:
            if isinstance(item, dict):
                description = item.get('description', item.get('responsibilities', item.get('responsibility', item.get('achievements', ''))))
                if isinstance(description, list):
                    description = '\n'.join(str(v).strip() for v in description if str(v).strip())
                normalized_item = {
                    'company': str(item.get('company', item.get('employer', ''))).strip(),
                    'position': str(item.get('position', item.get('title', item.get('role', '')))).strip(),
                    'start_date': str(item.get('start_date', item.get('start', ''))).strip(),
                    'end_date': str(item.get('end_date', item.get('end', ''))).strip(),
                    'description': str(description).strip(),
                }
                if any(normalized_item.values()) and not cls._looks_like_section_or_resume_title(''.join(normalized_item.values())):
                    normalized.append(normalized_item)
            elif isinstance(item, str):
                text = item.strip()
                if text and not cls._looks_like_section_or_resume_title(text):
                    normalized.append({
                        'company': text,
                        'position': '',
                        'start_date': '',
                        'end_date': '',
                        'description': '',
                    })
        return normalized
    
    @classmethod
    def _normalize_projects(cls, projects: list) -> list:
        """标准化项目经历"""
        if isinstance(projects, dict):
            projects = [projects]
        elif isinstance(projects, str):
            projects = [projects]
        normalized = []
        for item in projects:
            if isinstance(item, dict):
                techs = item.get('technologies', [])
                if not techs:
                    techs = item.get('tech_stack', item.get('technology_stack', []))
                if isinstance(techs, str):
                    techs = re.split(r'[,，、/|；;]', techs)
                description = item.get('description', item.get('responsibilities', item.get('result', '')))
                if isinstance(description, list):
                    description = '\n'.join(str(v).strip() for v in description if str(v).strip())
                description = str(description).strip()
                if not techs:
                    techs = cls._extract_technologies(description)
                normalized_item = {
                    'name': str(item.get('name', item.get('project_name', ''))).strip(),
                    'role': str(item.get('role', '')).strip(),
                    'description': description,
                    'technologies': [str(t).strip() for t in (techs if isinstance(techs, list) else []) if str(t).strip()],
                    'start_date': str(item.get('start_date', '')).strip(),
                    'end_date': str(item.get('end_date', '')).strip(),
                }
                has_text = any(value for key, value in normalized_item.items() if key != 'technologies') or bool(normalized_item['technologies'])
                if has_text and not cls._looks_like_section_or_resume_title(''.join(str(v) for k, v in normalized_item.items() if k != 'technologies')):
                    normalized.append(normalized_item)
            elif isinstance(item, str):
                text = item.strip()
                if text and not cls._looks_like_section_or_resume_title(text):
                    normalized.append({
                        'name': text,
                        'role': '',
                        'description': '',
                        'technologies': [],
                        'start_date': '',
                        'end_date': '',
                    })
        return normalized

    @classmethod
    def _extract_technologies(cls, text: str) -> list:
        """从描述文本中提取常见技术关键词"""
        if not text:
            return []
        known_techs = [
            'Python', 'Java', 'JavaScript', 'TypeScript', 'Go', 'C++', 'C#',
            'Django', 'Flask', 'FastAPI', 'Spring Boot', 'Vue', 'React',
            'MySQL', 'PostgreSQL', 'Redis', 'MongoDB', 'Elasticsearch',
            'Kafka', 'Spark', 'Hadoop', 'Docker', 'Kubernetes',
            'TensorFlow', 'PyTorch', 'Scikit-learn', 'Transformers',
            'NLP', '机器学习', '深度学习',
        ]
        found = []
        lower_text = text.lower()
        for tech in known_techs:
            if re.search(r'[\u4e00-\u9fa5]', tech):
                matched = tech.lower() in lower_text
            else:
                matched = bool(re.search(
                    rf'(?<![A-Za-z0-9+#.]){re.escape(tech)}(?![A-Za-z0-9+#.])',
                    text,
                    flags=re.IGNORECASE
                ))
            if matched and tech not in found:
                found.append(tech)
        return found
    
    @classmethod
    def _normalize_internships(cls, internships: list) -> list:
        """标准化实习经历"""
        normalized = []
        for item in internships:
            if isinstance(item, dict):
                normalized.append({
                    'company': str(item.get('company', '')).strip(),
                    'position': str(item.get('position', '')).strip(),
                    'start_date': str(item.get('start_date', '')).strip(),
                    'end_date': str(item.get('end_date', '')).strip(),
                    'description': str(item.get('description', '')).strip(),
                })
            elif isinstance(item, str):
                normalized.append({
                    'company': item.strip(),
                    'position': '',
                    'start_date': '',
                    'end_date': '',
                    'description': '',
                })
        return normalized
    
    @classmethod
    def _normalize_languages(cls, languages: list) -> list:
        """标准化语言能力"""
        normalized = []
        for item in languages:
            if isinstance(item, dict):
                normalized.append({
                    'language': str(item.get('language', '')).strip(),
                    'level': str(item.get('level', '')).strip(),
                })
            elif isinstance(item, str):
                parts = item.split('：') if '：' in item else item.split(':')
                if len(parts) == 2:
                    normalized.append({
                        'language': parts[0].strip(),
                        'level': parts[1].strip(),
                    })
                else:
                    normalized.append({
                        'language': item.strip(),
                        'level': '',
                    })
        return normalized
    
    @classmethod
    def validate_resume_data(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """验证简历数据格式"""
        errors = []
        
        if not data.get('name'):
            errors.append('姓名不能为空')
        
        phone = data.get('phone', '')
        if phone and not cls._is_valid_phone(phone):
            errors.append('电话号码格式不正确')
        
        email = data.get('email', '')
        if email and not cls._is_valid_email(email):
            errors.append('邮箱格式不正确')
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }
    
    @classmethod
    def _is_valid_phone(cls, phone: str) -> bool:
        """验证电话号码"""
        import re
        cleaned = re.sub(r'[\s-]', '', phone)
        return bool(re.match(r'^1[3-9]\d{9}$', cleaned))
    
    @classmethod
    def _is_valid_email(cls, email: str) -> bool:
        """验证邮箱地址"""
        import re
        return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))
    
    @classmethod
    def _extract_education_from_text(cls, text: str) -> list:
        """从文本中提取教育经历"""
        education = []
        education_patterns = [
            r'(本科|硕士|博士|大专|专科|高中|中专)\s*[：:]\s*([^\n，,；;]+)',
            r'(毕业院校|院校|学校)\s*[：:]\s*([^\n，,；;]+)',
            r'(专业)\s*[：:]\s*([^\n，,；;]+)',
            r'(\d{4})\s*[-~至到]\s*(\d{4})\s*(本科|硕士|博士|大专)',
            r'([\u4e00-\u9fa5]+大学|[\u4e00-\u9fa5]+学院)\s*(\d{4})[-~至到]\s*(\d{4}|\d{2})',
        ]
        
        for pattern in education_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                item = {
                    'school': '',
                    'degree': '',
                    'major': '',
                    'start_date': '',
                    'end_date': '',
                    'description': ' '.join(match),
                }
                if '大学' in match[0] or '学院' in match[0]:
                    item['school'] = match[0]
                    if len(match) > 1:
                        item['start_date'] = match[1]
                    if len(match) > 2:
                        item['end_date'] = match[2]
                elif match[0] in ['本科', '硕士', '博士', '大专', '专科', '高中', '中专']:
                    item['degree'] = match[0]
                    if len(match) > 1:
                        item['major'] = match[1]
                elif match[0] == '专业':
                    item['major'] = match[1] if len(match) > 1 else ''
                elif match[0] == '毕业院校' or match[0] == '院校' or match[0] == '学校':
                    item['school'] = match[1] if len(match) > 1 else ''
                
                if item['school'] or item['degree'] or item['major']:
                    education.append(item)
        
        return education
    
    @classmethod
    def _extract_experience_from_text(cls, text: str) -> tuple:
        """从文本中提取工作经历和实习经历"""
        experience = []
        internships = []
        
        experience_patterns = [
            r'(公司|企业|单位)\s*[：:]\s*([^\n，,；;]+)',
            r'(职位|岗位)\s*[：:]\s*([^\n，,；;]+)',
            r'(工作经验|工作年限)\s*[：:]\s*([^\n，,；;]+)',
            r'(\d{4})\s*[-~至到]\s*(\d{4}|\d{2}|至今|现在)\s*([^\n，,；;]+)',
        ]
        
        company_name = ''
        position_name = ''
        
        for pattern in experience_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if match[0] == '公司' or match[0] == '企业' or match[0] == '单位':
                    company_name = match[1] if len(match) > 1 else ''
                elif match[0] == '职位' or match[0] == '岗位':
                    position_name = match[1] if len(match) > 1 else ''
                elif re.match(r'^\d{4}$', match[0]):
                    start_date = match[0]
                    end_date = match[1] if len(match) > 1 else ''
                    desc = match[2] if len(match) > 2 else ''
                    is_internship = any(keyword in desc for keyword in ['实习', '见习'])
                    item = {
                        'company': company_name if company_name else '',
                        'position': position_name if position_name else '',
                        'start_date': start_date,
                        'end_date': end_date,
                        'description': desc,
                    }
                    if is_internship:
                        internships.append(item)
                    else:
                        experience.append(item)
        
        return experience, internships
    
    @classmethod
    def _extract_projects_from_text(cls, text: str) -> list:
        """从文本中提取项目经验"""
        projects = []
        
        project_patterns = [
            r'(项目名称|项目)\s*[：:]\s*([^\n，,；;]+)',
            r'(技术栈|技术)\s*[：:]\s*([^\n，,；;]+)',
            r'(负责|担任|职责)\s*[：:]\s*([^\n，,；;]+)',
        ]
        
        project_name = ''
        technologies = []
        
        for pattern in project_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if match[0] == '项目名称' or match[0] == '项目':
                    project_name = match[1] if len(match) > 1 else ''
                elif match[0] == '技术栈' or match[0] == '技术':
                    tech_str = match[1] if len(match) > 1 else ''
                    technologies = [t.strip() for t in re.split(r'[,，、/|]', tech_str) if t.strip()]
        
        if project_name or technologies:
            projects.append({
                'name': project_name,
                'role': '',
                'description': '',
                'technologies': technologies,
                'start_date': '',
                'end_date': '',
            })
        
        return projects
    
    @classmethod
    def _extract_skills_from_text(cls, text: str) -> list:
        """从文本中提取专业技能"""
        skills = []
        
        known_techs = [
            'Python', 'Java', 'JavaScript', 'TypeScript', 'Go', 'C++', 'C#', 'PHP', 'Ruby', 'Swift', 'Kotlin',
            'Django', 'Flask', 'FastAPI', 'Spring Boot', 'Vue', 'React', 'Angular', 'Node.js', 'Express',
            'MySQL', 'PostgreSQL', 'Redis', 'MongoDB', 'Elasticsearch', 'Oracle', 'SQL Server',
            'Kafka', 'Spark', 'Hadoop', 'Docker', 'Kubernetes', 'AWS', 'Azure', 'Linux',
            'TensorFlow', 'PyTorch', 'Scikit-learn', 'Transformers', 'NLP', '机器学习', '深度学习',
            'HTML', 'CSS', 'jQuery', 'Bootstrap', 'Webpack', 'Vite', 'WebRTC',
            'Git', 'Jenkins', 'CI/CD', 'DevOps', '微服务', 'RESTful', 'GraphQL',
        ]
        
        for tech in known_techs:
            if re.search(r'(?<![A-Za-z0-9+#.])' + re.escape(tech) + r'(?![A-Za-z0-9+#.])', text, re.IGNORECASE):
                skills.append(tech)
        
        skill_patterns = [
            r'(技能|专业技能|技术技能)\s*[：:]\s*([^\n，,；;]+)',
            r'(熟练掌握|掌握|了解)\s*[：:]\s*([^\n，,；;]+)',
        ]
        
        for pattern in skill_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                skill_str = match[1] if len(match) > 1 else ''
                found_skills = [s.strip() for s in re.split(r'[,，、/|]', skill_str) if s.strip()]
                for skill in found_skills:
                    if skill and skill not in skills:
                        skills.append(skill)
        
        return skills
    
    @classmethod
    def _extract_certificates_from_text(cls, text: str) -> list:
        """从文本中提取证书资质"""
        certificates = []
        
        certificate_patterns = [
            r'(证书|认证)\s*[：:]\s*([^\n，,；;]+)',
            r'(CET|四六级|英语)\s*([0-9]+)\s*(级)?',
            r'(计算机|软考|PMP|CFA|CPA|ACCA|FRM)\s*[^\n，,；;]*',
        ]
        
        known_certificates = [
            'CET-4', 'CET-6', '大学英语四级', '大学英语六级',
            '计算机二级', '计算机三级', '计算机四级',
            'PMP', '软考', '系统架构师', '软件设计师',
            'CFA', 'CPA', 'ACCA', 'FRM',
            'AWS认证', 'Azure认证', 'Google认证',
            '华为认证', '思科认证', 'Oracle认证',
        ]
        
        for cert in known_certificates:
            if cert in text:
                certificates.append(cert)
        
        for pattern in certificate_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                cert_str = ''.join(match).strip()
                if cert_str and cert_str not in certificates:
                    certificates.append(cert_str)
        
        return certificates
    
    @classmethod
    def _extract_summary_from_text(cls, text: str) -> str:
        """从文本中提取个人简介"""
        patterns = [
            r'(个人简介|自我介绍|自我评价|个人评价|简介)\s*[：:]\s*([\s\S]{20,})',
            r'(工作经历|项目经验|教育背景|专业技能)([\s\S]*?)(工作经历|项目经验|教育背景|专业技能|证书|获奖|语言|兴趣|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                result = match.group(1).strip()
                if len(result) > 50:
                    return result[:500]
        
        lines = text.split('\n')
        summary_lines = []
        for line in lines[:10]:
            if len(line) > 10 and not any(keyword in line for keyword in ['姓名', '电话', '邮箱', '手机']):
                summary_lines.append(line)
        
        return '\n'.join(summary_lines)[:500].strip()
