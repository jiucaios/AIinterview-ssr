from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_interview', '0016_assessmentgroup_jobconfiguration_assessment_group'),
    ]

    operations = [
        migrations.AddField(
            model_name='assessmentgroup',
            name='is_temporary',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
