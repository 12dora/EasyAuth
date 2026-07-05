from django.db import migrations

STATIC_KIND = "static_token"
UNAUTHENTICATABLE_CREDENTIAL_ERROR = (
    "存在 token_lookup 为空的 active 静态凭据; 这类凭据永远认证失败(401), "
    "属不可认证的垃圾行, 必须删除或轮换后再迁移, 不允许静默保留。"
)


def _assert_no_empty_static_lookup(apps, schema_editor):
    # 项目尚未上线: 不做惰性回填(需要明文 token, 只存哈希无法回填), 而是快速失败,
    # 让"迁移前创建、token_lookup='' 的静态凭据"这种不可认证状态显式暴露(BF-1)。
    _ = schema_editor
    app_credential = apps.get_model("applications", "AppCredential")
    has_garbage = app_credential.objects.filter(
        credential_type=STATIC_KIND,
        is_active=True,
        token_lookup="",
    ).exists()
    if has_garbage:
        raise RuntimeError(UNAUTHENTICATABLE_CREDENTIAL_ERROR)


class Migration(migrations.Migration):

    dependencies = [
        (
            "applications",
            "0016_remove_authorizationgroupaccesspolicy_applications_authorization_group_access_policy_max_duration_po",
        ),
    ]

    operations = [
        migrations.RunPython(_assert_no_empty_static_lookup, migrations.RunPython.noop),
    ]
