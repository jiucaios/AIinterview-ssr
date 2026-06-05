from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_interview', '0014_adminuser_hruser'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobconfiguration',
            name='job_match_status',
            field=models.CharField(db_index=True, default='pending', max_length=16),
        ),
        migrations.AddField(
            model_name='jobconfiguration',
            name='job_match_score',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='jobconfiguration',
            name='job_match_result',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='jobconfiguration',
            name='job_match_error',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='jobconfiguration',
            name='job_match_analyzed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
