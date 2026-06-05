# Generated manually to persist token usage records.

from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('ai_interview', '0009_candidate_email_alter_candidate_candidate_id_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='TokenUsage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('category', models.CharField(choices=[('resume_parsing', 'resume_parsing'), ('omni_interview', 'omni_interview'), ('answer_analysis', 'answer_analysis')], db_index=True, help_text='Token usage category', max_length=32)),
                ('input_tokens', models.IntegerField(default=0, help_text='Input token count')),
                ('output_tokens', models.IntegerField(default=0, help_text='Output token count')),
                ('total_tokens', models.IntegerField(default=0, help_text='Total token count')),
                ('model', models.CharField(blank=True, help_text='Model name', max_length=128)),
                ('metadata', models.JSONField(blank=True, default=dict, help_text='Extra metadata')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True, help_text='Created time')),
            ],
            options={
                'verbose_name': 'Token usage record',
                'verbose_name_plural': 'Token usage records',
                'db_table': 'ai_token_usage',
                'indexes': [
                    models.Index(fields=['category', 'created_at'], name='ai_token_us_categor_4cc17c_idx'),
                    models.Index(fields=['created_at'], name='ai_token_us_created_38a12f_idx'),
                ],
            },
        ),
    ]
