from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('ai_interview', '0010_tokenusage'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExternalAISession',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('request_id', models.CharField(db_index=True, max_length=128, unique=True)),
                ('external_session_id', models.CharField(db_index=True, max_length=64, unique=True)),
                ('scene', models.CharField(default='ai_interview', max_length=64)),
                ('status', models.CharField(choices=[('pending', 'pending'), ('in_progress', 'in_progress'), ('completed', 'completed'), ('failed', 'failed'), ('expired', 'expired'), ('cancelled', 'cancelled')], db_index=True, default='pending', max_length=32)),
                ('external_candidate_id', models.CharField(blank=True, max_length=128)),
                ('external_job_id', models.CharField(blank=True, max_length=128)),
                ('callback_url', models.URLField(max_length=1024)),
                ('request_payload', models.JSONField(blank=True, default=dict)),
                ('create_response', models.JSONField(blank=True, default=dict)),
                ('result_payload', models.JSONField(blank=True, default=dict)),
                ('downloaded_resume_path', models.CharField(blank=True, max_length=1024)),
                ('resume_downloaded_at', models.DateTimeField(blank=True, null=True)),
                ('callback_received', models.BooleanField(default=False)),
                ('callback_attempts', models.IntegerField(default=0)),
                ('callback_last_at', models.DateTimeField(blank=True, null=True)),
                ('callback_last_error', models.TextField(blank=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('candidate', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='external_ai_sessions', to='ai_interview.candidate')),
                ('job_config', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='external_ai_sessions', to='ai_interview.jobconfiguration')),
            ],
            options={
                'verbose_name': 'External AI interview session',
                'verbose_name_plural': 'External AI interview sessions',
                'db_table': 'ai_external_session',
                'indexes': [
                    models.Index(fields=['request_id', 'status'], name='ai_external_request_status_idx'),
                    models.Index(fields=['external_session_id', 'status'], name='ai_external_session_status_idx'),
                ],
            },
        ),
    ]
