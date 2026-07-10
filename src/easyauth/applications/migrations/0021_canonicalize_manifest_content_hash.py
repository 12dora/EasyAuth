from hashlib import sha256
import json

from django.db import migrations
from yaml import safe_load


def canonicalize_manifest_content_hash(apps, schema_editor):
    PermissionTemplateVersion = apps.get_model("applications", "PermissionTemplateVersion")
    for version in PermissionTemplateVersion.objects.all().iterator():
        manifest = safe_load(version.raw_template)
        if not isinstance(manifest, dict):
            raise ValueError("App manifest 顶层必须是对象。")
        canonical = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        version.content_hash = sha256(canonical.encode("utf-8")).hexdigest()
        version.save(update_fields=["content_hash"])


class Migration(migrations.Migration):
    dependencies = [("applications", "0020_remove_dependencyhealthsnapshot_applications_dependency_health_dependency_supported_and_more")]

    operations = [
        migrations.RunPython(canonicalize_manifest_content_hash, migrations.RunPython.noop),
    ]
