# Generated by Django 3.0.4 on 2020-04-15 17:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('books', '0006_auto_20200412_2302'),
    ]

    operations = [
        migrations.AlterField(
            model_name='book',
            name='visible',
            field=models.BooleanField(default=True, help_text='판매 중'),
        ),
    ]
