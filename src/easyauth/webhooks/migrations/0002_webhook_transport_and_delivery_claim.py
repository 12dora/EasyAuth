from urllib.parse import urlsplit

from django.db import migrations, models


def populate_allowed_hosts(apps, schema_editor):
    config_model = apps.get_model("webhooks", "AppWebhookConfig")
    for config in config_model.objects.all().iterator():
        hosts = set()
        for url in (
            config.approval_callback_url,
            config.handover_url,
            config.onboard_url,
        ):
            if not url:
                continue
            try:
                parsed = urlsplit(url)
                port = parsed.port
            except ValueError:
                continue
            if (
                parsed.scheme.lower() == "https"
                and parsed.hostname
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
                and port in (None, 443)
            ):
                hosts.add(parsed.hostname.lower())
        config.allowed_hosts = sorted(hosts)
        config.save(update_fields=["allowed_hosts"])


class Migration(migrations.Migration):
    dependencies = [("webhooks", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="appwebhookconfig",
            name="allowed_hosts",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="webhookdelivery",
            name="claim_token",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="webhookdelivery",
            name="generation",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="webhookdelivery",
            name="lease_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="webhookdelivery",
            constraint=models.CheckConstraint(
                condition=models.Q(("generation__gte", 1)),
                name="webhooks_delivery_generation_positive",
            ),
        ),
        migrations.RunPython(populate_allowed_hosts, migrations.RunPython.noop),
    ]
