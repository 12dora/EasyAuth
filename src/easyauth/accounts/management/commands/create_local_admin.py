from __future__ import annotations

from getpass import getpass
from typing import TYPE_CHECKING, final, override

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from easyauth.accounts.models import LocalAdminAccount

if TYPE_CHECKING:
    from argparse import ArgumentParser

ACCOUNT_EXISTS_ERROR = "账号 {username} 已存在; 如需重置密码请加 --update。"
PASSWORD_EMPTY_ERROR = "密码不能为空。"  # noqa: S105 - 错误提示文案, 不是密码值.
PASSWORD_MISMATCH_ERROR = "两次输入的密码不一致。"  # noqa: S105 - 错误提示文案, 不是密码值.


@final
class Command(BaseCommand):
    help = "创建(或用 --update 重置密码)本地超级管理员账号, 用于 /auth/local/ 登录。"

    @override
    def add_arguments(self, parser: ArgumentParser) -> None:
        _ = parser.add_argument("username", help="账号用户名(小写字母/数字/连字符/下划线)。")
        _ = parser.add_argument(
            "--password",
            default="",
            help="账号密码; 不提供则交互式输入。",
        )
        _ = parser.add_argument(
            "--update",
            action="store_true",
            help="账号已存在时重置其密码(缺省时已存在即报错)。",
        )
        _ = parser.add_argument(
            "--no-force-password-change",
            action="store_true",
            help="不要求该账号下次登录时修改密码(缺省创建/重置后都强制改密)。",
        )

    @override
    def handle(self, *args: object, **options: object) -> None:
        username = str(options.get("username", "")).strip()
        allow_update = bool(options.get("update", False))
        force_password_change = not bool(options.get("no_force_password_change", False))
        password = str(options.get("password", ""))
        if password == "":
            password = _prompt_password()

        existing = LocalAdminAccount.objects.filter(username=username).first()
        if existing is not None and not allow_update:
            raise CommandError(ACCOUNT_EXISTS_ERROR.format(username=username))

        account = existing or LocalAdminAccount(username=username)
        account.set_password(password)
        # 新建与重置密码默认都要求下次登录改密, 除非显式加 --no-force-password-change。
        account.must_change_password = force_password_change
        try:
            account.full_clean()
        except ValidationError as error:
            raise CommandError(str(error)) from error
        account.save()
        action = "已重置密码" if existing is not None else "已创建"
        force_hint = "下次登录须修改密码" if force_password_change else "未要求修改密码"
        self.stdout.write(
            f"本地管理员账号 {username} {action}({force_hint})。登录入口: /auth/local/",
        )


def _prompt_password() -> str:
    password = getpass("密码: ")
    if password == "":
        raise CommandError(PASSWORD_EMPTY_ERROR)
    confirmation = getpass("再次输入密码: ")
    if password != confirmation:
        raise CommandError(PASSWORD_MISMATCH_ERROR)
    return password
