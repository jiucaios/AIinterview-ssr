import os

from django.contrib.auth.hashers import make_password
from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import AdminUser, HRUser
from .hr_auth import AdminOrTokenRequiredMixin


def serialize_hr_user(user):
    return {
        'id': str(user.id),
        'username': user.username,
        'name': user.name,
        'email': user.email,
        'phone': user.phone,
        'is_active': user.is_active,
        'created_by': user.created_by.username if user.created_by else '',
        'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'updated_at': user.updated_at.isoformat() if user.updated_at else None,
    }


def admin_user_from_request(request):
    username = request.session.get('hr_auth_username') or ''
    if not username:
        return None
    return AdminUser.objects.filter(username=username, is_active=True).first()


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


class HRUserManagementView(AdminOrTokenRequiredMixin, APIView):
    login_redirect = True

    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), '..', 'hr_user_management.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                return HttpResponse(f.read(), content_type='text/html')
        return HttpResponse('HR user management page not found', status=404)


class HRUserListCreateView(AdminOrTokenRequiredMixin, APIView):
    def get(self, request):
        users = HRUser.objects.select_related('created_by').order_by('-created_at')
        return Response({'success': True, 'users': [serialize_hr_user(user) for user in users]})

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        password = (request.data.get('password') or '').strip()
        name = (request.data.get('name') or '').strip()
        email = (request.data.get('email') or '').strip()
        phone = (request.data.get('phone') or '').strip()
        is_active = parse_bool(request.data.get('is_active', True))

        if not username:
            return Response({'error': 'username is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not password:
            return Response({'error': 'password is required'}, status=status.HTTP_400_BAD_REQUEST)
        if HRUser.objects.filter(username=username).exists() or AdminUser.objects.filter(username=username).exists():
            return Response({'error': 'username already exists'}, status=status.HTTP_400_BAD_REQUEST)

        user = HRUser.objects.create(
            username=username,
            password_hash=make_password(password),
            name=name,
            email=email,
            phone=phone,
            is_active=is_active,
            created_by=admin_user_from_request(request),
        )
        return Response({'success': True, 'user': serialize_hr_user(user)}, status=status.HTTP_201_CREATED)


class HRUserDetailView(AdminOrTokenRequiredMixin, APIView):
    def patch(self, request, user_id):
        user = HRUser.objects.filter(id=user_id).select_related('created_by').first()
        if not user:
            return Response({'error': 'HR user not found'}, status=status.HTTP_404_NOT_FOUND)

        username = (request.data.get('username') or '').strip()
        password = (request.data.get('password') or '').strip()

        if username and username != user.username:
            if HRUser.objects.filter(username=username).exclude(id=user.id).exists() or AdminUser.objects.filter(username=username).exists():
                return Response({'error': 'username already exists'}, status=status.HTTP_400_BAD_REQUEST)
            user.username = username

        for field in ('name', 'email', 'phone'):
            if field in request.data:
                setattr(user, field, (request.data.get(field) or '').strip())

        if 'is_active' in request.data:
            user.is_active = parse_bool(request.data.get('is_active'))

        if password:
            user.password_hash = make_password(password)

        user.save()
        return Response({'success': True, 'user': serialize_hr_user(user)})

    def delete(self, request, user_id):
        user = HRUser.objects.filter(id=user_id).first()
        if not user:
            return Response({'error': 'HR user not found'}, status=status.HTTP_404_NOT_FOUND)
        user.delete()
        return Response({'success': True})
