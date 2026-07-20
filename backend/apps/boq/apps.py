from functools import partial
import json

from django.apps import AppConfig
from django.core.serializers.json import DjangoJSONEncoder


class BoqConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.boq"
    label = "boq"
    verbose_name = "BOQ Management"

    def ready(self) -> None:
        # psycopg3 JSONField dumps use stdlib json.dumps by default, which
        # rejects Decimal (e.g. Rate_Master.Size on analysis_data).
        try:
            from psycopg.types.json import set_json_dumps
        except ImportError:
            return
        set_json_dumps(partial(json.dumps, cls=DjangoJSONEncoder))
