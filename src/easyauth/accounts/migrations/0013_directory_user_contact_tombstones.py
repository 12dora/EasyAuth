from django.db import migrations, models


def normalize_directory_status(apps, schema_editor):
    del schema_editor
    mirror = apps.get_model("accounts", "DingTalkUserMirror")
    mirror.objects.filter(status__in=("inactive", "disabled")).update(status="disabled")
    mirror.objects.filter(status__in=("deleted", "departed")).update(status="departed")
    mirror.objects.exclude(status__in=("active", "disabled", "departed")).update(
        status="disabled",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0012_app_capability_and_directory_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="mobile",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="employee_number",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="is_tombstone",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="last_seen_generation",
            field=models.BigIntegerField(default=-1),
        ),
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="departed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(normalize_directory_status, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="dingtalkusermirror",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "active"),
                    ("disabled", "disabled"),
                    ("departed", "departed"),
                ],
                default="active",
                max_length=16,
            ),
        ),
    ]
