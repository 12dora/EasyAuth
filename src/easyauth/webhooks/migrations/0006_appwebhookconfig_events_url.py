from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0005_webhookdelivery_next_attempt_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="appwebhookconfig",
            name="events_url",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
    ]
