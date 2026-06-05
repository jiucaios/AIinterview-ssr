
import os
import django
from django.core.management.base import BaseCommand
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from ai_interview.models import Candidate, JobConfiguration, TalentProfile
from django.core.cache import cache


class Command(BaseCommand):
    help = '清空所有面试相关数据'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='确认删除所有数据',
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            self.stdout.write(self.style.WARNING(
                '警告：此操作将删除所有面试数据！\n'
                '请使用 --confirm 参数确认执行。\n'
                '将删除的数据：\n'
                '  - Candidate（候选人记录）\n'
                '  - TalentProfile（人才画像）\n'
                '  - JobConfiguration（职位配置）\n'
                '  - 缓存数据'
            ))
            return

        self.stdout.write(self.style.WARNING('开始清空面试数据...'))

        # 删除缓存
        self.stdout.write('清空缓存...')
        cache.clear()

        # 删除模型数据
        self.stdout.write('删除人才画像记录...')
        talent_count = TalentProfile.objects.count()
        TalentProfile.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'已删除 {talent_count} 条人才画像记录'))

        self.stdout.write('删除候选人记录...')
        candidate_count = Candidate.objects.count()
        Candidate.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'已删除 {candidate_count} 条候选人记录'))

        # 可选：删除职位配置（保留，可能会被复用）
        # self.stdout.write('删除职位配置...')
        # job_count = JobConfiguration.objects.count()
        # JobConfiguration.objects.all().delete()
        # self.stdout.write(self.style.SUCCESS(f'已删除 {job_count} 条职位配置'))

        self.stdout.write(self.style.SUCCESS('\n数据清空完成！'))

