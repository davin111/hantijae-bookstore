# Generated by Django 3.0.4 on 2020-03-29 19:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('books', '0002_auto_20200329_1353'),
    ]

    operations = [
        migrations.AddField(
            model_name='series',
            name='series_type',
            field=models.IntegerField(choices=[(1, 'series'), (2, 'normal')], default=1),
        ),
    ]
