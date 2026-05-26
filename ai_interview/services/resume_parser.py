import os
import json
import re
from typing import Dict, Any, Optional
from django.conf import settings
from .qwen_service import QwenService
from .prompts import get_prompt


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
        """从文件中提取文本内容"""
        text = ""
        
        try:
            if not os.path.exists(file_path):
                return ""
            
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return ""
            
            if extension == '.txt':
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            
            elif extension == '.pdf':
                text = cls._extract_pdf_text(file_path)
            
            elif extension == '.docx':
                text = cls._extract_docx_text(file_path)

            elif extension == '.doc':
                text = cls._extract_doc_fallback(file_path)
            
            elif extension in ['.jpg', '.jpeg', '.png']:
                text = cls._extract_image_text(file_path)
            
        except Exception as e:
            text = ""
        
        if text and (text.startswith('文件不存在') or text.startswith('文件为空') or 
                     text.startswith('文档内容为空') or text.startswith('文件读取错误')):
            return ""
        
        return text
    
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
        """使用AI解析简历文本"""
        api_key = QwenService.get_api_key()
        if not api_key:
            return {'error': '未配置API密钥，请检查.env文件中的DASHSCOPE_API_KEY'}
        
        try:
            system_prompt = get_prompt('resume_parser_system')
            user_prompt = get_prompt('resume_parser', resume_text=text_content)
            
            result = QwenService.generate_question(
                system_prompt=system_prompt,
                user_message=user_prompt,
                temperature=0.1,
                max_tokens=2000,
                use_advanced_model=False  # 简历解析使用基础模型
            )
            
            if not result:
                return {'error': 'AI解析失败，API返回为空', 'debug_info': {
                    'api_key_configured': bool(api_key),
                    'api_key_length': len(api_key),
                    'model': QwenService.get_model(),
                    'text_length': len(text_content)
                }}
            
            if any(keyword in result for keyword in ['API调用', '失败', '异常', '错误', '状态码', '未配置']):
                return {'error': f'AI解析失败: {result}', 'debug_info': {
                    'api_key_configured': bool(api_key),
                    'model': QwenService.get_model()
                }}
            
            try:
                parsed_json = cls._extract_json_from_response(result)
                ai_result = cls._normalize_result(parsed_json)
                fallback_result = cls._parse_fallback(text_content, result)
                return cls._merge_results(ai_result, fallback_result)
            except json.JSONDecodeError:
                return cls._parse_fallback(text_content, result)
        
        except Exception as e:
            import traceback
            return {'error': f'AI解析错误: {str(e)}', 'debug_info': {
                'exception_type': type(e).__name__,
                'traceback': traceback.format_exc()[:500]
            }}
    
    @classmethod
    def _parse_fallback(cls, text_content: str, raw_response: str = "") -> Dict[str, Any]:
        """解析失败时的备用方案，手动提取关键信息"""
        result = {
            'name': '',
            'phone': '',
            'email': '',
            'education': [],
            'experience': [],
            'skills': [],
            'certificates': [],
            'projects': [],
            'summary': text_content[:500] if text_content else '',
        }
        
        if text_content:
            sections = cls._split_resume_sections(text_content)
            result.update(cls._extract_basic_info(text_content))
            result['summary'] = cls._extract_summary(sections, text_content)
            result['education'] = cls._extract_education(sections)
            result['experience'] = cls._extract_experience(sections.get('experience', ''))
            result['internships'] = cls._extract_experience(sections.get('internships', ''))
            result['projects'] = cls._extract_projects(sections.get('projects', ''))
            result['skills'] = cls._extract_list_items(sections.get('skills', ''))
            result['certificates'] = cls._extract_list_items(sections.get('certificates', ''))
            result['awards'] = cls._extract_list_items(sections.get('awards', ''))
            result['languages'] = cls._extract_languages(sections.get('languages', ''))
            result['hobbies'] = cls._extract_list_items(sections.get('hobbies', ''))
        
        return cls._normalize_result(result)

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
            elif key == 'summary' and len(str(current).strip()) < 20 and fallback_value:
                merged[key] = fallback_value
        return cls._normalize_result(merged)

    @classmethod
    def _split_resume_sections(cls, text: str) -> Dict[str, str]:
        """按简历常见标题拆分文本区块"""
        section_aliases = {
            'summary': ['个人简介', '自我介绍', '自我评价', '个人评价', '个人总结', '职业总结'],
            'education': ['教育经历', '教育背景', '教育情况', '学历背景'],
            'experience': ['工作经历', '工作经验', '工作履历', '职业经历'],
            'internships': ['实习经历', '实习经验'],
            'projects': ['项目经历', '项目经验', '项目实践', '项目介绍'],
            'skills': ['专业技能', '技能', '技能清单', '技术技能', '职业技能'],
            'certificates': ['证书', '证书与资质', '资格证书', '资质证书'],
            'awards': ['获奖情况', '荣誉奖项', '所获荣誉', '奖项'],
            'languages': ['语言能力', '语言水平', '外语能力'],
            'hobbies': ['兴趣爱好', '爱好'],
        }
        title_to_key = {title: key for key, titles in section_aliases.items() for title in titles}
        title_pattern = '|'.join(re.escape(title) for title in title_to_key)
        lines = [line.strip() for line in re.split(r'[\r\n]+', text) if line.strip()]
        sections = {'basic': []}
        current = 'basic'

        for line in lines:
            normalized = re.sub(r'^[#\-*•\s]+', '', line).strip()
            normalized = re.sub(r'[：:]\s*$', '', normalized)
            if re.match(r'^(姓名|名字|电话|手机|邮箱|性别|年龄|所在地|现居地|居住地|求职意向|期望职位|期望薪资)\s+', normalized):
                sections.setdefault('basic', []).append(normalized)
                continue
            inline_match = re.match(rf'^({title_pattern})[：:]\s*(.+)$', normalized)
            if inline_match:
                current = title_to_key[inline_match.group(1)]
                sections.setdefault(current, [])
                sections[current].append(inline_match.group(2).strip())
                continue
            match = re.fullmatch(title_pattern, normalized)
            if match:
                current = title_to_key[match.group(0)]
                sections.setdefault(current, [])
                continue
            sections.setdefault(current, []).append(line)

        return {key: '\n'.join(value) for key, value in sections.items()}

    @classmethod
    def _extract_basic_info(cls, text: str) -> Dict[str, Any]:
        """提取姓名、联系方式和基础字段"""
        result = {
            'name': '',
            'phone': '',
            'email': '',
            'age': '',
            'gender': '',
            'location': '',
            'objective': '',
            'expected_salary': '',
            'work_type': '',
        }

        patterns = {
            'name': [
                r'(?:姓名|名字|Name|name)\s*[：:]\s*([\u4e00-\u9fa5·]{2,8}|[A-Za-z][A-Za-z\s]{1,40})',
                r'(?:姓名|名字|Name|name)\s+([\u4e00-\u9fa5·]{2,8}|[A-Za-z][A-Za-z\s]{1,40})',
                r'^\s*([\u4e00-\u9fa5·]{2,4})\s*$',
            ],
            'age': [r'(?:年龄|Age|age)\s*[：:\s]\s*([0-9]{1,2}\s*岁?)'],
            'gender': [r'(?:性别|Gender|gender)\s*[：:\s]\s*([男女])'],
            'location': [r'(?:所在地|现居地|居住地|城市|地址)\s*[：:\s]\s*([^\n\r，,；;]{2,30})'],
            'objective': [r'(?:求职意向|应聘岗位|目标岗位|期望职位)\s*[：:\s]\s*([^\n\r]{2,80})'],
            'expected_salary': [r'(?:期望薪资|薪资要求)\s*[：:\s]\s*([^\n\r]{2,40})'],
            'work_type': [r'(?:工作类型|求职类型)\s*[：:\s]\s*([^\n\r]{2,30})'],
        }

        phone_match = re.search(r'(?:\+?86[-\s]?)?1[3-9]\d{9}', text)
        if phone_match:
            result['phone'] = re.sub(r'[\s-]', '', phone_match.group(0))
            result['phone'] = re.sub(r'^\+?86', '', result['phone'])

        email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
        if email_match:
            result['email'] = email_match.group(0)

        for field, field_patterns in patterns.items():
            for pattern in field_patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
                if match:
                    value = match.group(1).strip()
                    if field == 'name' and any(token in value for token in ['简历', '个人', '求职']):
                        continue
                    result[field] = value
                    break

        return result

    @classmethod
    def _extract_summary(cls, sections: Dict[str, str], text: str) -> str:
        summary = sections.get('summary', '').strip()
        if summary:
            return summary
        for pattern in [
            r'(?:个人简介|自我介绍|自我评价|个人评价)[：:]\s*([\s\S]{20,500}?)(?:\n\s*(?:教育|工作|项目|技能|证书|获奖|语言|兴趣)|$)',
        ]:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return text[:500].strip()

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
    def _normalize_result(cls, result: Dict[str, Any]) -> Dict[str, Any]:
        """标准化解析结果"""
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
        result['skills'] = [s.strip() for s in result['skills'] if isinstance(s, str) and s.strip()]
        result['certificates'] = [c.strip() for c in result['certificates'] if isinstance(c, str) and c.strip()]
        result['awards'] = [a.strip() for a in result['awards'] if isinstance(a, str) and a.strip()]
        result['hobbies'] = [h.strip() for h in result['hobbies'] if isinstance(h, str) and h.strip()]
        
        return result
    
    @classmethod
    def _normalize_education(cls, education: list) -> list:
        """标准化教育经历"""
        normalized = []
        for item in education:
            if isinstance(item, dict):
                normalized.append({
                    'school': str(item.get('school', '')).strip(),
                    'degree': str(item.get('degree', '')).strip(),
                    'major': str(item.get('major', '')).strip(),
                    'start_date': str(item.get('start_date', '')).strip(),
                    'end_date': str(item.get('end_date', '')).strip(),
                    'description': str(item.get('description', '')).strip(),
                })
            elif isinstance(item, str):
                normalized.append({
                    'school': item.strip(),
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
        normalized = []
        for item in experience:
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
    def _normalize_projects(cls, projects: list) -> list:
        """标准化项目经历"""
        normalized = []
        for item in projects:
            if isinstance(item, dict):
                techs = item.get('technologies', [])
                if isinstance(techs, str):
                    techs = techs.split(',')
                description = str(item.get('description', '')).strip()
                if not techs:
                    techs = cls._extract_technologies(description)
                normalized.append({
                    'name': str(item.get('name', '')).strip(),
                    'role': str(item.get('role', '')).strip(),
                    'description': description,
                    'technologies': [str(t).strip() for t in (techs if isinstance(techs, list) else []) if str(t).strip()],
                    'start_date': str(item.get('start_date', '')).strip(),
                    'end_date': str(item.get('end_date', '')).strip(),
                })
            elif isinstance(item, str):
                normalized.append({
                    'name': item.strip(),
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
