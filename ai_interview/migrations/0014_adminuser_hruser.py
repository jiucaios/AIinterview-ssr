import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


DEFAULT_ADMIN_USERNAME = 'admin'
DEFAULT_ADMIN_PASSWORD = 'admin123456'


def create_default_admin(apps, schema_editor):
    AdminUser = apps.get_model('ai_interview', 'AdminUser')
    from django.contrib.auth.hashers import make_password

    admin, created = AdminUser.objects.get_or_create(
        username=DEFAULT_ADMIN_USERNAME,
        defaults={
            'password_hash': make_password(DEFAULT_ADMIN_PASSWORD),
            'is_active': True,
        },
    )
    if not created and not admin.password_hash:
        admin.password_hash = make_password(DEFAULT_ADMIN_PASSWORD)
        admin.is_active = True
        admin.updated_at = timezone.now()
        admin.save(update_fields=['password_hash', 'is_active', 'updated_at'])


def remove_default_admin(apps, schema_editor):
    AdminUser = apps.get_model('ai_interview', 'AdminUser')
    AdminUser.objects.filter(username=DEFAULT_ADMIN_USERNAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ai_interview', '0013_jobconfiguration_resume_parse_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='AdminUser',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('username', models.CharField(db_index=True, max_length=64, unique=True)),
                ('password_hash', models.CharField(max_length=256)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('last_login_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Admin user',
                'verbose_name_plural': 'Admin users',
                'db_table': 'ai_admin_user',
            },
        ),
        migrations.CreateModel(
            name='HRUser',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('username', models.CharField(db_index=True, max_length=64, unique=True)),
                ('password_hash', models.CharField(max_length=256)),
                ('name', models.CharField(blank=True, max_length=64)),
                ('email', models.EmailField(blank=True, max_length=128)),
                ('phone', models.CharField(blank=True, max_length=32)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('last_login_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_hr_users', to='ai_interview.adminuser')),
            ],
            options={
                'verbose_name': 'HR user',
                'verbose_name_plural': 'HR users',
                'db_table': 'ai_hr_user',
            },
        ),
        migrations.RunPython(create_default_admin, remove_default_admin),
    ]
