import os
import uuid
import tempfile
import datetime
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..services.resume_parser import ResumeParser
from ..models import TalentProfile


class ResumeParserView(APIView):
    def post(self, request):
        try:
            import json
            if 'file' not in request.FILES:
                return Response(
                    {'error': '请上传简历文件', 'debug': {
                        'files_keys': list(request.FILES.keys()),
                        'data_keys': list(request.data.keys()),
                        'content_type': request.content_type
                    }},
                    status=status.HTTP_400_BAD_REQUEST
                )

            file = request.FILES['file']
            file_name = file.name
            save_to_db = request.data.get('save_to_db', False)

            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as temp_file:
                for chunk in file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            try:
                result = ResumeParser.parse_resume(temp_file_path, file_name)

                if 'error' in result:
                    return Response(
                        {**result, 'debug_info': {
                            'file_name': file_name,
                            'file_size': file.size,
                            'temp_file_path': temp_file_path,
                            'file_extension': os.path.splitext(file_name)[1]
                        }},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                result['file_name'] = file_name
                result['parsed_at'] = datetime.datetime.now().isoformat()

                if save_to_db and result.get('name'):
                    candidate_id = result.get('phone') or result.get('email') or f"CAND_{uuid.uuid4().hex[:8]}"

                    profile = TalentProfile.objects.create(
                        candidate_id=candidate_id,
                        session_id=f"resume_{uuid.uuid4().hex}",
                        session_incomplete=False,
                        raw_resume=result,
                        job_config={},
                        hard_fields_results={},
                        project_role_results={},
                        confidence_score=0.8,
                        incomplete_reasons=[],
                    )
                    result['profile_id'] = str(profile.id)

                return Response(result, status=status.HTTP_200_OK)

            finally:
                os.unlink(temp_file_path)

        except Exception as e:
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ResumeValidateView(APIView):
    def post(self, request):
        try:
            resume_data = request.data.get('resume_data', {})

            validation_result = ResumeParser.validate_resume_data(resume_data)

            return Response(validation_result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'服务器错误: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )