# ruff: noqa: RUF012
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0013_directory_user_contact_tombstones"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="localadminpasskey",
            constraint=models.CheckConstraint(
                condition=models.Q(sign_count__gte=0),
                name="accounts_passkey_sc_gte_0",
            ),
        ),
    ]
