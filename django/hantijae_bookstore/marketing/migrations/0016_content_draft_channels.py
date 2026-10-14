from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('marketing', '0015_ad_book_title')]
    operations = [migrations.AlterField(
        model_name='draft', name='channel',
        field=models.CharField(max_length=20, choices=[
            ('blog', '블로그 글'), ('instagram', '인스타 글'), ('links', '서점 링크 공지'),
            ('short', '짧은 소개'), ('letter', '보낼 글'), ('recruit', '서평단 모집 글'), ('editor', '편집 후기'),
        ]),
    ), migrations.AlterField(
        model_name='signal', name='kind',
        field=models.CharField(max_length=20, choices=[
            ('news', '저자 소식'), ('selection', '공공 선정'), ('social', '운영진 SNS'),
            ('moment', '대화 속 계기'), ('review', '독자 서평'), ('peer', '참고 출판사'),
        ]),
    )]
