from __future__ import annotations

from django.db import migrations, models


def renumber_duplicate_versions(apps, schema_editor):
    """历史重复版本按 id 顺序重排, 保证 (user, app, version) 唯一。"""
    access_grant = apps.get_model("grants", "AccessGrant")
    seen: dict[tuple[int, int], set[int]] = {}
    for grant in access_grant.objects.order_by("user_id", "app_id", "version", "id"):
        key = (grant.user_id, grant.app_id)
        used = seen.setdefault(key, set())
        version = grant.version
        if version in used:
            version = max(used) + 1
            grant.version = version
            grant.save(update_fields=["version"])
        used.add(version)


class Migration(migrations.Migration):
    dependencies = [
        ("grants", "0002_scoped_grants"),
    ]

    operations = [
        migrations.RunPython(renumber_duplicate_versions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="accessgrant",
            constraint=models.UniqueConstraint(
                fields=("user", "app", "version"),
                name="grants_access_grant_version_unique",
            ),
        ),
    ]
