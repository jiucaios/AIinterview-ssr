from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_interview", "0011_externalaisession"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobconfiguration",
            name="interview_type",
            field=models.CharField(
                choices=[
                    ("initial_interview", "初次面试"),
                    ("discussion", "面谈"),
                ],
                db_index=True,
                default="initial_interview",
                help_text="面试类别",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="jobconfiguration",
            name="recruitment_requirements",
            field=models.TextField(blank=True, help_text="面谈招聘要求"),
        ),
    ]
