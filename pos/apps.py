from django.apps import AppConfig

class PosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pos'

    def ready(self):
        import pos.signals  # noqa: Import signals to connect receivers