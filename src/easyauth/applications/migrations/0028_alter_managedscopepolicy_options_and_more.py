# ruff: noqa: ANN001, ANN201, E501, Q000, RUF012
# pyright: reportAny=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false
import django.db.models.deletion
from django.db import migrations, models


class ManagedScopePolicyMigrationError(RuntimeError):
    pass


def assert_managed_scope_policy_targets(apps, _schema_editor):
    policy_model = apps.get_model("applications", "ManagedScopePolicy")
    grant_model = apps.get_model("applications", "AuthorizationGroupGrant")
    bad_policy_ids = []
    for policy in policy_model.objects.all().order_by("id"):
        if policy.target_type == "app_default":
            if policy.target_id != policy.app_id:
                bad_policy_ids.append(policy.id)
                continue
            continue
        if policy.target_type != "authorization_group_grant":
            bad_policy_ids.append(policy.id)
            continue
        grant = grant_model.objects.filter(id=policy.target_id).first()
        if grant is None or grant.authorization_group.app_id != policy.app_id:
            bad_policy_ids.append(policy.id)
    if bad_policy_ids:
        sample = ", ".join(str(item) for item in bad_policy_ids[:20])
        message = (
            "ManagedScopePolicy 目标外键迁移被阻断: 存在孤儿或跨 App 策略, "
            f"count={len(bad_policy_ids)}, sample_ids={sample}"
        )
        raise ManagedScopePolicyMigrationError(message)


def migrate_managed_scope_policy_targets(apps, _schema_editor):
    policy_model = apps.get_model("applications", "ManagedScopePolicy")
    for policy in policy_model.objects.filter(
        target_type="authorization_group_grant",
    ).order_by("id"):
        policy.authorization_group_grant_id = policy.target_id
        policy.save(update_fields=["authorization_group_grant"])


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0027_notification_channel_directory_scope'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='managedscopepolicy',
            options={'ordering': ['app__app_key', 'target_type', 'authorization_group_grant_id', 'scope']},
        ),
        migrations.RemoveConstraint(
            model_name='managedscopepolicy',
            name='applications_managed_scope_policy_target_unique',
        ),
        migrations.RunPython(assert_managed_scope_policy_targets, migrations.RunPython.noop),
        migrations.AddField(
            model_name='managedscopepolicy',
            name='authorization_group_grant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='managed_scope_policies', to='applications.authorizationgroupgrant'),
        ),
        migrations.RunPython(migrate_managed_scope_policy_targets, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='managedscopepolicy',
            name='target_id',
        ),
        migrations.AddConstraint(
            model_name='managedscopepolicy',
            constraint=models.UniqueConstraint(condition=models.Q(('target_type', 'app_default')), fields=('app', 'target_type', 'scope'), name='applications_managed_scope_policy_app_default_unique'),
        ),
        migrations.AddConstraint(
            model_name='managedscopepolicy',
            constraint=models.UniqueConstraint(condition=models.Q(('target_type', 'authorization_group_grant')), fields=('authorization_group_grant', 'scope'), name='applications_managed_scope_policy_grant_unique'),
        ),
        migrations.AddConstraint(
            model_name='managedscopepolicy',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('authorization_group_grant__isnull', True), ('target_type', 'app_default')), models.Q(('authorization_group_grant__isnull', False), ('target_type', 'authorization_group_grant')), _connector='OR'), name='applications_managed_scope_policy_target_shape'),
        ),
    ]
