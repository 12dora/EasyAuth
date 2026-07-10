from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_usermirror_department_changed_at")]

    operations = [
        migrations.AddField(
            model_name="localadminaccount",
            name="session_version",
            field=models.PositiveBigIntegerField(default=1),
        ),
    ]
