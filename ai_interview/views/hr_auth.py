import os

from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.contrib.auth.hashers import check_password
from rest_framework.views import APIView

from ..models import AdminUser, HRUser


HR_AUTH_SESSION_KEY = 'hr_authenticated'
HR_AUTH_USERNAME_SESSION_KEY = 'hr_auth_username'
HR_AUTH_ROLE_SESSION_KEY = 'hr_auth_role'


def get_expected_hr_token():
    return os.getenv('EXTERNAL_AI_SESSION_TOKEN', '').strip()


def request_has_valid_hr_token(request):
    expected_token = get_expected_hr_token()
    if not expected_token:
        return False

    auth_header = request.headers.get('Authorization', '').strip()
    token = ''
    if auth_header.lower().startswith('bearer '):
        token = auth_header[7:].strip()

    token = token or request.GET.get('token', '').strip()

    return bool(token) and constant_time_compare(token, expected_token)


class HRAuthRequiredMixin:
    login_redirect = False

    def dispatch(self, request, *args, **kwargs):
        if request_has_valid_hr_token(request):
            return super().dispatch(request, *args, **kwargs)

        if request.session.get(HR_AUTH_SESSION_KEY):
            return super().dispatch(request, *args, **kwargs)

        if self.login_redirect:
            return HttpResponseRedirect('/api/ai-interview/hr/login/')

        return JsonResponse({'error': 'HR access authentication required'}, status=401)


class AdminOrTokenRequiredMixin(HRAuthRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request_has_valid_hr_token(request):
            return super(HRAuthRequiredMixin, self).dispatch(request, *args, **kwargs)

        if not request.session.get(HR_AUTH_SESSION_KEY):
            if self.login_redirect:
                return HttpResponseRedirect('/api/ai-interview/hr/login/')
            return JsonResponse({'error': 'HR access authentication required'}, status=401)

        if request.session.get(HR_AUTH_ROLE_SESSION_KEY) == 'admin':
            return super(HRAuthRequiredMixin, self).dispatch(request, *args, **kwargs)

        return JsonResponse({'error': 'Admin access required'}, status=403)


class HRAuthContextView(HRAuthRequiredMixin, APIView):
    def get(self, request):
        role = 'token' if request_has_valid_hr_token(request) else request.session.get(HR_AUTH_ROLE_SESSION_KEY, 'hr')
        return JsonResponse({
            'authenticated': True,
            'role': role,
            'can_manage_hr_users': role in ('admin', 'token'),
        })


class HRLoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        if request.session.get(HR_AUTH_SESSION_KEY):
            return HttpResponseRedirect('/api/ai-interview/hr/')

        return HttpResponse(self._render_login_page(), content_type='text/html')

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        password = (request.data.get('password') or '').strip()
        auth_user = authenticate_hr_console_user(username, password)

        if auth_user:
            request.session[HR_AUTH_SESSION_KEY] = True
            request.session[HR_AUTH_USERNAME_SESSION_KEY] = username
            request.session[HR_AUTH_ROLE_SESSION_KEY] = auth_user['role']
            return HttpResponseRedirect('/api/ai-interview/hr/')

        return HttpResponse(
            self._render_login_page('Invalid username or password'),
            status=401,
            content_type='text/html',
        )

    def _render_login_page(self, error_message=''):
        error_html = f'<div class="error">{error_message}</div>' if error_message else ''
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI面试系统 - HR登录</title>
    <style>
        :root {{
            --bg: #07111f;
            --panel: rgba(9, 23, 42, 0.86);
            --panel-strong: rgba(12, 31, 56, 0.94);
            --line: rgba(116, 167, 226, 0.24);
            --text: #edf6ff;
            --muted: #9eb3c9;
            --accent: #38bdf8;
            --accent-2: #2dd4bf;
            --danger: #ff6b7a;
        }}
        * {{
            box-sizing: border-box;
        }}
        body {{
            margin: 0;
            min-height: 100vh;
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
            background:
                linear-gradient(120deg, rgba(45, 212, 191, 0.15), transparent 32%),
                linear-gradient(300deg, rgba(56, 189, 248, 0.2), transparent 38%),
                var(--bg);
            overflow-x: hidden;
        }}
        body::before {{
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background-image:
                linear-gradient(rgba(148, 184, 216, 0.055) 1px, transparent 1px),
                linear-gradient(90deg, rgba(148, 184, 216, 0.055) 1px, transparent 1px);
            background-size: 48px 48px;
            mask-image: linear-gradient(to bottom, rgba(0,0,0,0.8), transparent 88%);
        }}
        .shell {{
            position: relative;
            z-index: 1;
            min-height: 100vh;
            display: grid;
            grid-template-columns: minmax(0, 1.05fr) minmax(360px, 440px);
            align-items: center;
            gap: 42px;
            width: min(1120px, calc(100vw - 40px));
            margin: 0 auto;
            padding: 40px 0;
        }}
        .brand-panel {{
            min-height: 520px;
            padding: 34px;
            border: 1px solid var(--line);
            border-radius: 14px;
            background: linear-gradient(160deg, rgba(10, 30, 54, 0.78), rgba(7, 17, 31, 0.52));
            box-shadow: 0 28px 90px rgba(0, 0, 0, 0.28);
            overflow: hidden;
        }}
        .brand-mark {{
            width: 44px;
            height: 44px;
            display: grid;
            place-items: center;
            border-radius: 10px;
            border: 1px solid rgba(56, 189, 248, 0.38);
            background: rgba(56, 189, 248, 0.12);
            color: #b9f2ff;
            font-weight: 900;
            font-size: 17px;
        }}
        .eyebrow {{
            margin-top: 34px;
            color: var(--accent-2);
            font-size: 13px;
            font-weight: 800;
        }}
        .brand-panel h1 {{
            width: min(620px, 100%);
            margin: 12px 0 14px;
            font-size: 46px;
            line-height: 1.08;
            letter-spacing: 0;
        }}
        .brand-panel p {{
            width: min(560px, 100%);
            margin: 0;
            color: var(--muted);
            font-size: 16px;
            line-height: 1.8;
        }}
        .signal-grid {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
            margin-top: 34px;
        }}
        .signal-card {{
            min-height: 92px;
            padding: 14px;
            border: 1px solid rgba(116, 167, 226, 0.2);
            border-radius: 8px;
            background: rgba(5, 16, 31, 0.48);
        }}
        .signal-value {{
            color: #dff9ff;
            font-size: 22px;
            font-weight: 900;
        }}
        .signal-label {{
            margin-top: 8px;
            color: var(--muted);
            font-size: 12px;
        }}
        .scanline {{
            position: relative;
            height: 96px;
            margin-top: 34px;
            border: 1px solid rgba(56, 189, 248, 0.2);
            border-radius: 8px;
            background:
                repeating-linear-gradient(90deg, rgba(56, 189, 248, 0.18) 0 2px, transparent 2px 14px),
                linear-gradient(90deg, rgba(45, 212, 191, 0.18), rgba(56, 189, 248, 0.04));
            overflow: hidden;
        }}
        .scanline::after {{
            content: "";
            position: absolute;
            inset: 0;
            width: 38%;
            background: linear-gradient(90deg, transparent, rgba(237, 246, 255, 0.22), transparent);
            animation: sweep 3s linear infinite;
        }}
        @keyframes sweep {{
            from {{ transform: translateX(-110%); }}
            to {{ transform: translateX(280%); }}
        }}
        .login-panel {{
            padding: 30px;
            border: 1px solid rgba(116, 167, 226, 0.28);
            border-radius: 14px;
            background: var(--panel);
            box-shadow: 0 24px 70px rgba(0, 0, 0, 0.32);
            backdrop-filter: blur(16px);
        }}
        .login-panel h2 {{
            margin: 0;
            font-size: 24px;
            line-height: 1.2;
            letter-spacing: 0;
        }}
        .login-subtitle {{
            margin: 8px 0 24px;
            color: var(--muted);
            font-size: 13px;
        }}
        label {{
            display: block;
            margin: 16px 0 8px;
            color: #b7c7da;
            font-size: 13px;
            font-weight: 700;
        }}
        input {{
            width: 100%;
            height: 46px;
            padding: 0 13px;
            border: 1px solid rgba(116, 167, 226, 0.28);
            border-radius: 8px;
            background: rgba(4, 12, 24, 0.72);
            color: var(--text);
            font-size: 15px;
            outline: none;
            transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
        }}
        input:focus {{
            border-color: rgba(56, 189, 248, 0.76);
            background: rgba(4, 12, 24, 0.88);
            box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.12);
        }}
        button {{
            width: 100%;
            height: 46px;
            margin-top: 24px;
            border: 0;
            border-radius: 8px;
            background: linear-gradient(135deg, #2dd4bf 0%, #38bdf8 100%);
            color: #04111f;
            font-size: 15px;
            font-weight: 900;
            cursor: pointer;
            box-shadow: 0 14px 30px rgba(56, 189, 248, 0.22);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }}
        button:hover {{
            transform: translateY(-1px);
            box-shadow: 0 18px 38px rgba(56, 189, 248, 0.3);
        }}
        .error {{
            margin: 0 0 16px;
            padding: 11px 12px;
            border: 1px solid rgba(255, 107, 122, 0.35);
            border-radius: 8px;
            background: rgba(255, 107, 122, 0.1);
            color: #ffd1d7;
            font-size: 14px;
        }}
        .secure-note {{
            margin-top: 18px;
            color: var(--muted);
            font-size: 12px;
            line-height: 1.6;
        }}
        @media (max-width: 860px) {{
            .shell {{
                grid-template-columns: 1fr;
                gap: 18px;
                width: min(520px, calc(100vw - 28px));
            }}
            .brand-panel {{
                min-height: auto;
                padding: 24px;
            }}
            .brand-panel h1 {{
                font-size: 32px;
            }}
            .signal-grid {{
                grid-template-columns: 1fr;
            }}
            .scanline {{
                display: none;
            }}
        }}
    </style>
</head>
<body>
    <main class="shell">
        <section class="brand-panel" aria-label="系统概览">
            <div class="brand-mark">AI</div>
            <div class="eyebrow">INTELLIGENT INTERVIEW OPERATIONS</div>
            <h1>AI面试管理中枢</h1>
            <p>统一管理候选人、岗位评估、飞书任务与面试报告，让招聘流程保持清晰、可追踪、可复盘。</p>
            <div class="signal-grid">
                <div class="signal-card">
                    <div class="signal-value">24/7</div>
                    <div class="signal-label">在线面试任务接入</div>
                </div>
                <div class="signal-card">
                    <div class="signal-value">AI</div>
                    <div class="signal-label">简历解析与问答评估</div>
                </div>
                <div class="signal-card">
                    <div class="signal-value">HR</div>
                    <div class="signal-label">权限隔离与后台管理</div>
                </div>
            </div>
            <div class="scanline" aria-hidden="true"></div>
        </section>
        <form class="login-panel" method="post" action="/api/ai-interview/hr/login/">
            <h2>安全登录</h2>
            <div class="login-subtitle">请输入 HR 工作台账号密码继续访问</div>
            {error_html}
            <label for="username">账号</label>
            <input id="username" name="username" autocomplete="username" required>
            <label for="password">密码</label>
            <input id="password" name="password" type="password" autocomplete="current-password" required>
            <button type="submit">进入工作台</button>
            <div class="secure-note">登录状态仅保存在当前浏览器会话中。请在公共设备上完成操作后退出账号。</div>
        </form>
    </main>
</body>
</html>'''


class HRLogoutView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        request.session.pop(HR_AUTH_SESSION_KEY, None)
        request.session.pop(HR_AUTH_USERNAME_SESSION_KEY, None)
        request.session.pop(HR_AUTH_ROLE_SESSION_KEY, None)
        return HttpResponseRedirect('/api/ai-interview/hr/login/')

    def post(self, request):
        request.session.pop(HR_AUTH_SESSION_KEY, None)
        request.session.pop(HR_AUTH_USERNAME_SESSION_KEY, None)
        request.session.pop(HR_AUTH_ROLE_SESSION_KEY, None)
        return JsonResponse({'success': True})


def authenticate_hr_console_user(username, password):
    if not username or not password:
        return None

    admin = AdminUser.objects.filter(username=username, is_active=True).first()
    if admin and check_password(password, admin.password_hash):
        admin.last_login_at = timezone.now()
        admin.save(update_fields=['last_login_at', 'updated_at'])
        return {'role': 'admin', 'user': admin}

    hr_user = HRUser.objects.filter(username=username, is_active=True).first()
    if hr_user and check_password(password, hr_user.password_hash):
        hr_user.last_login_at = timezone.now()
        hr_user.save(update_fields=['last_login_at', 'updated_at'])
        return {'role': 'hr', 'user': hr_user}

    return None
