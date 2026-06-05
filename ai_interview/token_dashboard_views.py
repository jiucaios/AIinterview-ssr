import os
from django.http import HttpResponse, JsonResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .services.token_tracker import TokenTracker
from .views.hr_auth import AdminOrTokenRequiredMixin


class TokenDashboardView(AdminOrTokenRequiredMixin, APIView):
    """Token计算台页面"""
    
    login_redirect = True

    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), 'token_dashboard.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='text/html')
        return HttpResponse("Token计算台页面未找到", status=404)


class TokenDashboardDataView(AdminOrTokenRequiredMixin, APIView):
    """Token计算台数据API - 直接从数据库读取"""
    
    def get(self, request):
        try:
            stats = TokenTracker.get_stats_from_database()
            
            return Response({
                'success': True,
                'data': stats,
                'category_names': TokenTracker.CATEGORY_NAMES
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {'success': False, 'error': f'获取统计数据失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class TokenDashboardClearView(AdminOrTokenRequiredMixin, APIView):
    """清除Token统计数据"""
    
    def post(self, request):
        try:
            category = request.data.get('category')
            
            if category and category not in TokenTracker.CATEGORY_NAMES:
                return Response(
                    {'success': False, 'error': '无效的类别'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            success = TokenTracker.clear_stats(category)
            
            if success:
                message = f"已清除{'所有' if not category else TokenTracker.CATEGORY_NAMES.get(category, category)}统计数据"
                return Response({
                    'success': True,
                    'message': message
                }, status=status.HTTP_200_OK)
            else:
                return Response(
                    {'success': False, 'error': '清除失败'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            return Response(
                {'success': False, 'error': f'清除失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
