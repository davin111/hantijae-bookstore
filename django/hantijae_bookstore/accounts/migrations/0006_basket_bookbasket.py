# Generated by Django 3.0.4 on 2020-04-01 19:34

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('books', '0005_auto_20200401_1716'),
        ('accounts', '0005_auto_20200401_1929'),
    ]

    operations = [
        migrations.CreateModel(
            name='Basket',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('update_at', models.DateTimeField(auto_now=True)),
                ('max_book_count', models.PositiveSmallIntegerField(default=10)),
                ('max_price', models.PositiveIntegerField(default=100000)),
                ('status', models.IntegerField(choices=[(1, 'none'), (2, 'ordered'), (3, 'paid'), (4, 'completed')], default=1)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='baskets', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'accounts_basket',
            },
        ),
        migrations.CreateModel(
            name='BookBasket',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('update_at', models.DateTimeField(auto_now=True)),
                ('count', models.PositiveSmallIntegerField(default=1)),
                ('basket', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='books', to='accounts.Basket')),
                ('book', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='baskets', to='books.Book')),
            ],
            options={
                'db_table': 'accounts_bookbasket',
            },
        ),
    ]
