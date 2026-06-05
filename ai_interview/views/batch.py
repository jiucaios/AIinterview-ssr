import os

from django.http import HttpResponse
from rest_framework.views import APIView

from .hr_auth import HRAuthRequiredMixin


class BatchInterviewView(HRAuthRequiredMixin, APIView):
    login_redirect = True

    def get(self, request):
        template_path = os.path.join(os.path.dirname(__file__), '..', 'batch_interview.html')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                return HttpResponse(f.read(), content_type='text/html')
        return HttpResponse('Batch interview page not found', status=404)
