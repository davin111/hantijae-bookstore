from django.apps import AppConfig


class IntakeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'intake'
    verbose_name = '신간 등록 자동화'
