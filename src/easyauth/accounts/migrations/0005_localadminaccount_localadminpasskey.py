from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("accounts", "0004_dingtalkusermirror_avatar_dingtalkusermirror_title"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.CreateModel(
            name="LocalAdminAccount",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "username",
                    models.CharField(
                        max_length=64,
                        unique=True,
                        validators=[
                            django.core.validators.RegexValidator(
                                "^[a-z0-9][a-z0-9_-]*$",
                                "用户名只允许小写字母、数字、连字符和下划线, 且以字母或数字开头。",
                            ),
                        ],
                    ),
                ),
                ("password_hash", models.CharField(max_length=255)),
                ("totp_secret", models.CharField(blank=True, max_length=64)),
                ("totp_enabled", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["username"],
            },
        ),
        migrations.CreateModel(
            name="LocalAdminPasskey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("credential_id", models.TextField(unique=True)),
                ("public_key", models.TextField()),
                ("sign_count", models.IntegerField(default=0)),
                ("transports", models.JSONField(default=list)),
                ("name", models.CharField(blank=True, max_length=100)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="passkeys",
                        to="accounts.localadminaccount",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
            },
        ),
    ]
