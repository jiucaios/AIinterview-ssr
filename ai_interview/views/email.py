import os
import time
import mimetypes
from html import escape
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .hr_auth import HRAuthRequiredMixin

EMAIL_LOGO_FILENAME = 'email-logo.jpg'
EMAIL_CONTACT = 'jiucaios@qq.com'
EMAIL_SUPPORT_PHONE = '17337075112'


def get_email_logo_path():
    return os.path.join(os.path.dirname(__file__), '..', 'images', EMAIL_LOGO_FILENAME)


def build_interview_email_text(candidate_name, job_title, interview_url):
    name = candidate_name or '候选人'
    title = job_title or 'AI应用工程师'
    return (
        f"{name}，您好！\n\n"
        f"感谢您投递我司{title}职位，我们对您的简历印象深刻，现诚邀您参加AI面试\n"
        "请在收到邮件的三天内完成面试，完成AI面试后有机会进入下一阶段。\n\n"
        f"面试链接为：\n{interview_url}\n\n"
        "面试链接已绑定您的个人信息，请勿转发给他人！！！\n\n"
        f"·如果您还有其他疑问，请联系您的专属HR或发送邮件至{EMAIL_CONTACT}\n"
        f"·若遇在面试中遇到技术问题，请致电{EMAIL_SUPPORT_PHONE}以获得技术支持\n\n"
        "成就个体，共创未来"
    )


def build_logo_html(logo_cid, size):
    if logo_cid:
        return (
            f'<img src="cid:{logo_cid}" width="{size}" height="{size}" alt="未来世界 Logo" '
            f'style="display:block;width:{size}px;height:{size}px;object-fit:contain;border:0;">'
        )
    return f'<div style="width:{size}px;height:{size}px;background:#ffffff;"></div>'


def build_interview_email_html(candidate_name, job_title, interview_url, logo_cid=None):
    name = escape(candidate_name or '候选人')
    title = escape(job_title or 'AI应用工程师')
    url = (interview_url or '').strip()
    safe_url = escape(url, quote=True)
    link_html = (
        f'<a href="{safe_url}" target="_blank" '
        'style="color:#1266cc;font-weight:700;text-decoration:none;word-break:break-all;">'
        f'{safe_url}</a>'
        if safe_url else
        '<span style="color:#666666;">面试链接将在此显示</span>'
    )
    top_logo = build_logo_html(logo_cid, 76)
    footer_logo = build_logo_html(logo_cid, 56)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI面试邀请</title>
</head>
<body style="margin:0;padding:0;background:#eeeeee;font-family:Arial,'Microsoft YaHei',sans-serif;color:#111111;">
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background:#eeeeee;margin:0;padding:16px 0;">
        <tr>
            <td align="center">
                <table width="960" cellpadding="0" cellspacing="0" role="presentation" style="width:960px;max-width:960px;background:#ffffff;">
                    <tr>
                        <td style="height:132px;padding:28px 34px;background:#ffffff;background-image:linear-gradient(180deg,#e7e7e7 0%,#ffffff 78%);">
                            <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                                <tr>
                                    <td align="left" valign="top">
                                        <div style="width:76px;height:76px;background:#ffffff;border:1px solid #eeeeee;">{top_logo}</div>
                                    </td>
                                    <td align="right" valign="top" style="padding-top:22px;color:#858585;font-size:34px;line-height:1;font-weight:800;letter-spacing:0;">
                                        未来世界
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td align="center" style="padding:28px 0 22px;">
                            <table width="760" cellpadding="0" cellspacing="0" role="presentation" style="width:760px;max-width:760px;">
                                <tr>
                                    <td style="font-size:18px;line-height:2.1;color:#111111;">
                                        <p style="margin:0 0 24px;font-size:21px;line-height:1.8;font-weight:700;">{name}，您好！</p>
                                        <p style="margin:0 0 12px;text-indent:2em;">感谢您投递我司{title}职位，我们对您的简历印象深刻，现诚邀您参加AI面试</p>
                                        <p style="margin:0 0 12px;">请在收到邮件的三天内完成面试，完成AI面试后有机会进入下一阶段。</p>
                                        <p style="margin:4px 0 12px;">面试链接为：</p>
                                        <p style="margin:0 0 12px;">{link_html}</p>
                                        <p style="margin:14px 0 12px;font-size:19px;line-height:1.7;font-weight:800;color:#000000;">面试链接已绑定您的个人信息，请勿转发给他人！！！</p>
                                        <p style="margin:0 0 12px;">·如果您还有其他疑问，请联系您的专属HR或发送邮件至{EMAIL_CONTACT}</p>
                                        <p style="margin:0 0 12px;">·若遇在面试中遇到技术问题，请致电{EMAIL_SUPPORT_PHONE}以获得技术支持</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td align="center" style="padding:0 0 44px;">
                            <table width="760" cellpadding="0" cellspacing="0" role="presentation" style="width:760px;max-width:760px;border-top:1px solid #efefef;">
                                <tr>
                                    <td align="center" style="padding-top:28px;">
                                        <div style="width:56px;height:56px;background:#ffffff;border:1px solid #eeeeee;margin:0 auto 14px;">{footer_logo}</div>
                                        <div style="font-size:21px;color:#111111;line-height:1.5;margin-bottom:8px;">成就个体，共创未来</div>
                                        <div style="font-size:15px;line-height:1.5;color:#006fd6;">
                                            <a href="#" style="color:#006fd6;text-decoration:none;">隐私政策</a> · <a href="#" style="color:#006fd6;text-decoration:none;">保留所有权利</a>
                                        </div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>'''


def send_message_via_smtp(smtplib, smtp_server, smtp_username, smtp_password, message):
    smtp_timeout = int(os.getenv('SMTP_TIMEOUT', '30'))
    smtp_test_mode = os.getenv('SMTP_TEST_MODE', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

    if smtp_test_mode:
        log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"email_{time.strftime('%Y%m%d_%H%M%S')}.log")
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(f"=== 模拟发送邮件 ===\n")
            f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"收件人: {message['To']}\n")
            f.write(f"发件人: {message['From']}\n")
            f.write(f"主题: {message['Subject']}\n")
            f.write(f"\n邮件内容:\n")
            f.write(message.as_string())
        print(f"[测试模式] 邮件已记录到日志文件: {log_file}")
        return

    def send_with_starttls(port):
        server = smtplib.SMTP(smtp_server, port, timeout=smtp_timeout)
        try:
            server.ehlo()
            server.starttls()
            server.ehlo()
            try:
                server.login(smtp_username, smtp_password)
            except smtplib.SMTPAuthenticationError as auth_err:
                raise Exception(f'登录失败: {str(auth_err)}。请检查SMTP账户是否开启了POP3/SMTP服务，以及授权码是否正确。')
            server.sendmail(smtp_username, [message['To']], message.as_string())
            server.quit()
        except smtplib.SMTPServerDisconnected:
            raise Exception('SMTP连接被服务器断开。可能原因：1) 登录失败导致连接关闭 2) 服务器超时')
        except Exception:
            try:
                if server.sock is not None:
                    server.quit()
            except Exception:
                pass
            raise

    def send_with_ssl(port):
        server = smtplib.SMTP_SSL(smtp_server, port, timeout=smtp_timeout)
        try:
            try:
                server.login(smtp_username, smtp_password)
            except smtplib.SMTPAuthenticationError as auth_err:
                raise Exception(f'登录失败: {str(auth_err)}。请检查SMTP账户是否开启了POP3/SMTP服务，以及授权码是否正确。')
            server.sendmail(smtp_username, [message['To']], message.as_string())
            server.quit()
        except smtplib.SMTPServerDisconnected:
            raise Exception('SMTP连接被服务器断开。可能原因：1) 登录失败导致连接关闭 2) 服务器超时')
        except Exception:
            try:
                if server.sock is not None:
                    server.quit()
            except Exception:
                pass
            raise

    errors = []
    try:
        send_with_starttls(587)
        return
    except smtplib.SMTPAuthenticationError as e:
        raise e
    except (smtplib.SMTPException, TimeoutError, OSError) as e:
        errors.append(f'STARTTLS(587): {str(e)}')

    try:
        send_with_ssl(465)
        return
    except smtplib.SMTPAuthenticationError as e:
        raise e
    except (smtplib.SMTPException, TimeoutError, OSError) as e:
        errors.append(f'SSL(465): {str(e)}')

    raise Exception(f'SMTP连接失败: {", ".join(errors)}。可能原因：1) 网络防火墙阻止了SMTP连接 2) SMTP服务器地址或端口配置错误 3) 服务器暂时不可用。')


class SendEmailView(HRAuthRequiredMixin, APIView):
    login_redirect = True

    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), '..', 'send_email.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("发送邮件页面未找到", status=404)


class SendEmailImageView(HRAuthRequiredMixin, APIView):
    def get(self, request, filename):
        if filename != EMAIL_LOGO_FILENAME:
            return HttpResponse(status=404)

        image_path = get_email_logo_path()
        if not os.path.exists(image_path):
            return HttpResponse(status=404)

        content_type = mimetypes.guess_type(image_path)[0] or 'application/octet-stream'
        with open(image_path, 'rb') as image_file:
            return HttpResponse(image_file.read(), content_type=content_type)


class SendEmailAPIView(HRAuthRequiredMixin, APIView):
    def post(self, request):
        try:
            import smtplib
            from email.header import Header
            from email.mime.image import MIMEImage
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.utils import formataddr

            email_to = (request.data.get('email_to') or '').strip()
            candidate_name = (request.data.get('candidate_name') or '').strip()
            job_title = (request.data.get('job_title') or 'AI应用工程师').strip()
            subject = (request.data.get('subject') or 'AI面试邀请').strip() or 'AI面试邀请'
            interview_url = (request.data.get('interview_url') or '').strip()

            if not email_to:
                return Response(
                    {'error': '收件人邮箱不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not interview_url:
                return Response(
                    {'error': '面试链接不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            smtp_server = os.getenv('SMTP_SERVER', 'smtp.qq.com')
            smtp_username = os.getenv('SMTP_USERNAME', '2601413168@qq.com')
            smtp_password = os.getenv('SMTP_PASSWORD', 'vybtlcjfbrxrecbj')

            logo_path = get_email_logo_path()
            logo_cid = 'email-logo' if os.path.exists(logo_path) else None
            text_body = build_interview_email_text(candidate_name, job_title, interview_url)
            html_body = build_interview_email_html(candidate_name, job_title, interview_url, logo_cid)

            msg = MIMEMultipart('related')
            msg['From'] = formataddr((str(Header('AI面试系统', 'utf-8')), smtp_username))
            msg['To'] = email_to
            msg['Subject'] = Header(subject, 'utf-8')

            alternative = MIMEMultipart('alternative')
            alternative.attach(MIMEText(text_body, 'plain', 'utf-8'))
            alternative.attach(MIMEText(html_body, 'html', 'utf-8'))
            msg.attach(alternative)

            if logo_cid:
                with open(logo_path, 'rb') as logo_file:
                    logo = MIMEImage(logo_file.read())
                logo.add_header('Content-ID', f'<{logo_cid}>')
                logo.add_header('Content-Disposition', 'inline', filename=EMAIL_LOGO_FILENAME)
                msg.attach(logo)

            send_message_via_smtp(smtplib, smtp_server, smtp_username, smtp_password, msg)

            return Response({
                'success': True,
                'message': '邮件发送成功'
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'发送邮件失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
