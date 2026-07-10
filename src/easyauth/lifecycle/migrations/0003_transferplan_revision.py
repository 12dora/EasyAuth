from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("lifecycle", "0002_remove_handoverappaction_lifecycle_action_status_supported_and_more")]

    operations = [
        migrations.AddField(
            model_name="transferplan",
            name="revision",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
