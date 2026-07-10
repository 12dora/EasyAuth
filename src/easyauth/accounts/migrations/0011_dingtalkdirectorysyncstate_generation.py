from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_localadminaccount_session_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="dingtalkdirectorysyncstate",
            name="generation",
            field=models.BigIntegerField(default=-1),
        ),
    ]
