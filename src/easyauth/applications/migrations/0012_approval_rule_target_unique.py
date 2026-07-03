from __future__ import annotations

from django.db import migrations, models


def dedupe_approval_rules(apps, schema_editor):
    """同一目标保留最新一行(最大 id, 即最近一次导入写入的行), 删除其余重复规则。"""
    approval_rule = apps.get_model("applications", "ApprovalRule")
    keep_ids: dict[tuple[str, int, int | None, int | None], int] = {}
    for rule_id, app_id, group_id, permission_id in approval_rule.objects.values_list(
        "id",
        "app_id",
        "authorization_group_id",
        "permission_id",
    ).order_by("id"):
        if group_id is not None:
            key = ("group", app_id, group_id, None)
        elif permission_id is not None:
            key = ("permission", app_id, None, permission_id)
        else:
            continue
        keep_ids[key] = rule_id
    kept = set(keep_ids.values())
    duplicate_ids = [
        rule_id
        for rule_id in approval_rule.objects.values_list("id", flat=True)
        if rule_id not in kept
    ]
    if duplicate_ids:
        approval_rule.objects.filter(id__in=duplicate_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0011_app_credential_token_lookup"),
    ]

    operations = [
        migrations.RunPython(dedupe_approval_rules, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="approvalrule",
            constraint=models.UniqueConstraint(
                condition=models.Q(("authorization_group__isnull", False)),
                fields=("app", "authorization_group"),
                name="applications_approval_rule_group_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="approvalrule",
            constraint=models.UniqueConstraint(
                condition=models.Q(("permission__isnull", False)),
                fields=("app", "permission"),
                name="applications_approval_rule_permission_unique",
            ),
        ),
    ]
