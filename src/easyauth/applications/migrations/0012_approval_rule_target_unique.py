from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation
    from django.db.migrations.state import StateApps


class _MigrationQuerySet(Protocol):
    def __iter__(self) -> Iterator[tuple[int, int, int | None, int | None]]: ...

    def order_by(self, *field_names: str) -> _MigrationQuerySet: ...


class _MigrationManager(Protocol):
    def values_list(self, *field_names: str) -> _MigrationQuerySet: ...


class _HistoricalApprovalRule(Protocol):
    objects: _MigrationManager


def assert_no_duplicate_approval_rules(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = schema_editor
    approval_rule = cast(
        "_HistoricalApprovalRule",
        apps.get_model("applications", "ApprovalRule"),
    )
    seen: set[tuple[str, int, int | None, int | None]] = set()
    duplicate_ids: list[int] = []
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
        if key in seen:
            duplicate_ids.append(rule_id)
        seen.add(key)
    if duplicate_ids:
        message = (
            "EA-AUD-023 迁移被阻断: applications.0012 不能按最大 id 保留并静默删除重复审批规则。"
            f" count={len(duplicate_ids)}, sample_ids={duplicate_ids[:5]}。"
            "请先显式合并重复目标的审批规则。"
        )
        raise RuntimeError(message)


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0011_app_credential_token_lookup"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunPython(assert_no_duplicate_approval_rules, migrations.RunPython.noop),
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
