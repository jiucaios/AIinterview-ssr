import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ai_interview', '0015_jobconfiguration_job_match'),
    ]

    operations = [
        migrations.CreateModel(
            name='AssessmentGroup',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('candidate_name', models.CharField(db_index=True, max_length=64)),
                ('candidate_email', models.EmailField(db_index=True, max_length=128)),
                ('job_key', models.CharField(db_index=True, max_length=256)),
                ('job_name', models.CharField(max_length=256)),
                ('group_number', models.IntegerField(default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('candidate', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='assessment_groups', to='ai_interview.candidate')),
            ],
            options={
                'verbose_name': '评估组',
                'verbose_name_plural': '评估组',
                'db_table': 'ai_assessment_group',
                'unique_together': {('candidate_email', 'candidate_name', 'job_key', 'group_number')},
            },
        ),
        migrations.AddField(
            model_name='jobconfiguration',
            name='assessment_group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='job_configs', to='ai_interview.assessmentgroup'),
        ),
        migrations.AddIndex(
            model_name='assessmentgroup',
            index=models.Index(fields=['candidate_email', 'candidate_name', 'job_key'], name='ai_assessme_candida_069e8b_idx'),
        ),
    ]
