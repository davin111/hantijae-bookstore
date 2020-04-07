# Generated by Django 3.0.4 on 2020-04-07 20:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_user_notifiable'),
    ]

    operations = [
        migrations.AddField(
            model_name='basket',
            name='address',
            field=models.CharField(blank=True, max_length=3000),
        ),
        migrations.AddField(
            model_name='basket',
            name='email',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name='basket',
            name='first_name',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='basket',
            name='last_name',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='basket',
            name='payer',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='basket',
            name='phone_number',
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name='basket',
            name='postal_code',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='basket',
            name='receiver_first_name',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='basket',
            name='receiver_last_name',
            field=models.CharField(blank=True, max_length=300),
        ),
    ]