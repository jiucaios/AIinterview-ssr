from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_interview', '0012_jobconfiguration_interview_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobconfiguration',
            name='resume_parse_status',
            field=models.CharField(db_index=True, default='completed', max_length=16),
        ),
        migrations.AddField(
            model_name='jobconfiguration',
            name='resume_parse_error',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='jobconfiguration',
            name='resume_source_path',
            field=models.CharField(blank=True, max_length=1024),
        ),
    ]
