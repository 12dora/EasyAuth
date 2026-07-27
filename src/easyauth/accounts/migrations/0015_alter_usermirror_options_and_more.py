# ruff: noqa: ANN001, ANN201, E501, Q000, RUF012
# pyright: reportAny=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false
from django.conf import settings
from django.db import migrations, models
from django.db.models import Count, Q


class UserMirrorBindingMigrationError(RuntimeError):
    pass


def backfill_bound_dingtalk_source(apps, _schema_editor):
    """已绑定钉钉身份的历史行补齐 source_slug。

    AddField 只会把新列填成 NULL，所以任何在本迁移之前就完成绑定的 UserMirror
    （corp_id/userid 非空）都会落进 assert_dingtalk_binding_scope 的“形状违规”
    分支。这里按 (corp_id, userid) 回查 DingTalkUserMirror 取真实来源；查不到时
    退回配置的默认目录来源，保证同一 corp 下的绑定仍然可解释。
    """

    user_model = apps.get_model("accounts", "UserMirror")
    dingtalk_mirror_model = apps.get_model("accounts", "DingTalkUserMirror")
    default_slug = str(getattr(settings, "EASYAUTH_AUTHENTIK_DINGTALK_SOURCE_SLUG", "dingtalk") or "dingtalk")

    bound = user_model.objects.filter(
        Q(dingtalk_source_slug__isnull=True) | Q(dingtalk_source_slug=""),
    ).exclude(dingtalk_corp_id="").exclude(dingtalk_userid="")
    for user in bound.iterator():
        slug = (
            dingtalk_mirror_model.objects.filter(
                corp_id=user.dingtalk_corp_id,
                user_id=user.dingtalk_userid,
            )
            .values_list("source_slug", flat=True)
            .first()
        )
        user.dingtalk_source_slug = slug or default_slug
        user.save(update_fields=["dingtalk_source_slug"])


def assert_dingtalk_binding_scope(apps, _schema_editor):
    user_model = apps.get_model("accounts", "UserMirror")
    source_empty = Q(dingtalk_source_slug__isnull=True) | Q(dingtalk_source_slug="")
    source_present = ~source_empty
    corp_empty = Q(dingtalk_corp_id="")
    corp_present = ~corp_empty
    user_empty = Q(dingtalk_userid="")
    user_present = ~user_empty
    invalid_binding_ids = list(
        user_model.objects.exclude(
            (source_empty & corp_empty & user_empty)
            | (source_present & corp_present & user_present),
        )
        .order_by("id")
        .values_list("id", flat=True)[:20],
    )
    if invalid_binding_ids:
        sample = ", ".join(str(item) for item in invalid_binding_ids)
        message = (
            "UserMirror 钉钉身份形状迁移被阻断: source_slug/corp_id/userid 必须同时为空或同时非空, "
            f"sample_ids={sample}"
        )
        raise UserMirrorBindingMigrationError(message)

    duplicates = list(
        user_model.objects.exclude(dingtalk_source_slug="")
        .exclude(dingtalk_userid="")
        .exclude(dingtalk_corp_id="")
        .values("dingtalk_source_slug", "dingtalk_corp_id", "dingtalk_userid")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .order_by("dingtalk_source_slug", "dingtalk_corp_id", "dingtalk_userid")[:20],
    )
    if duplicates:
        sample = ", ".join(
            (
                f"{item['dingtalk_source_slug']}:"
                f"{item['dingtalk_corp_id']}:{item['dingtalk_userid']}({item['count']})"
            )
            for item in duplicates
        )
        message = (
            "UserMirror 钉钉身份唯一约束迁移被阻断: 存在重复绑定, "
            f"sample={sample}"
        )
        raise UserMirrorBindingMigrationError(message)


def normalize_unbound_dingtalk_source(apps, _schema_editor):
    user_model = apps.get_model("accounts", "UserMirror")
    _ = user_model.objects.filter(
        dingtalk_source_slug__isnull=True,
        dingtalk_corp_id="",
        dingtalk_userid="",
    ).update(dingtalk_source_slug="")


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0014_oidc_authority_and_passkey_sign_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='usermirror',
            name='dingtalk_source_slug',
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.RunPython(backfill_bound_dingtalk_source, migrations.RunPython.noop),
        migrations.RunPython(assert_dingtalk_binding_scope, migrations.RunPython.noop),
        migrations.RunPython(normalize_unbound_dingtalk_source, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='usermirror',
            name='dingtalk_source_slug',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AlterModelOptions(
            name='usermirror',
            options={'base_manager_name': 'objects', 'ordering': ['authentik_user_id']},
        ),
        migrations.RemoveIndex(
            model_name='usermirror',
            name='accounts_user_dingtalk_idx',
        ),
        migrations.AddIndex(
            model_name='usermirror',
            index=models.Index(fields=['dingtalk_source_slug', 'dingtalk_corp_id', 'dingtalk_userid'], name='accounts_user_dingtalk_idx'),
        ),
        migrations.AddConstraint(
            model_name='usermirror',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('dingtalk_source_slug', ''), ('dingtalk_corp_id', ''), ('dingtalk_userid', '')), models.Q(models.Q(('dingtalk_source_slug', ''), _negated=True), models.Q(('dingtalk_corp_id', ''), _negated=True), models.Q(('dingtalk_userid', ''), _negated=True)), _connector='OR'), name='accounts_user_dingtalk_binding_shape'),
        ),
        migrations.AddConstraint(
            model_name='usermirror',
            constraint=models.UniqueConstraint(condition=models.Q(models.Q(('dingtalk_source_slug', ''), _negated=True), models.Q(('dingtalk_corp_id', ''), _negated=True), models.Q(('dingtalk_userid', ''), _negated=True)), fields=('dingtalk_source_slug', 'dingtalk_corp_id', 'dingtalk_userid'), name='accounts_user_dingtalk_binding_unique'),
        ),
    ]
