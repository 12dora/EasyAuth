# 本地超级管理员 TOTP 与 step-up 重认证。
# 本模块不导入 local_admin, 避免循环依赖; 节流回调由门面在调用时注入。
from __future__ import annotations

import base64
import io
import time
from secrets import compare_digest, token_urlsafe
from typing import TYPE_CHECKING, Final

import pyotp
import qrcode
import qrcode.image.svg
from django.contrib.auth import hashers
from django.db.models import Q
from django.utils import timezone

from easyauth.accounts.local_admin_common import session_mapping, webauthn_rp_name
from easyauth.accounts.models import LocalAdminAccount

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest

TOTP_SETUP_SESSION_KEY: Final = "easyauth_local_admin_totp_setup"
TOTP_SETUP_TTL_SECONDS: Final = 600
TOTP_CODE_LENGTH: Final = 6
STEP_UP_OK: Final = "ok"
STEP_UP_THROTTLED: Final = "throttled"
STEP_UP_INVALID: Final = "invalid"

# 用与真实账号相同的 hasher 预算一个 dummy 哈希, 让"账号不存在/停用"分支也跑一次常量时间校验,
# 消除本地管理员用户名可经响应时序枚举的侧信道(BS-15)。
_DUMMY_PASSWORD_HASH: Final = hashers.make_password("easyauth-timing-equalizer")


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def run_dummy_password_hash(password: str) -> None:
    _ = hashers.check_password(password, _DUMMY_PASSWORD_HASH)  # pyright: ignore[reportUnknownMemberType]


def matched_totp_timestep(secret: str, code: str) -> int | None:
    # 返回命中的 timestep(counter), 未命中返回 None; 供一次性消费判定。
    normalized = code.strip().replace(" ", "")
    if secret == "" or len(normalized) != TOTP_CODE_LENGTH or not normalized.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    current_step = totp.timecode(timezone.now())
    for offset in (-1, 0, 1):
        step = current_step + offset
        if compare_digest(totp.generate_otp(step), normalized):
            return step
    return None


def verify_totp_code(secret: str, code: str) -> bool:
    # 无状态校验(不消费 timestep): 仅用于对 session 中尚未落库的注册种子做确认。
    return matched_totp_timestep(secret, code) is not None


def check_step_up(
    account: LocalAdminAccount,
    password: str,
    *,
    login_is_throttled: Callable[[str], bool],
    record_login_failure: Callable[[str], None],
) -> str:
    # 因子变更(禁用 TOTP / 增删 passkey)前的 step-up 重认证, 复用登录节流计数,
    # 关闭"任意已登录会话即可无限试探并改动第二因子"的会话内提权(BS-14)。
    if login_is_throttled(account.username):
        return STEP_UP_THROTTLED
    if not password or not account.check_password(password):
        record_login_failure(account.username)
        return STEP_UP_INVALID
    return STEP_UP_OK


def verify_and_consume_totp(account: LocalAdminAccount, code: str) -> bool:
    # 一次性消费: 拒绝 <= 已记录 timestep 的验证码, 成功后前移 totp_last_timestep,
    # 防止窗口内(约 90s)重放满足第二因子(BS-7, RFC 6238 §5.2)。
    step = matched_totp_timestep(account.totp_secret, code)
    if step is None:
        return False
    # 用带条件的原子 UPDATE 前移 timestep, 避免"读-判-写"的 TOCTOU: 两个并发请求只有一个能
    # 把 totp_last_timestep 推进到 step, 另一个 update 命中 0 行即判为重放。
    consumed = (
        LocalAdminAccount.objects.filter(pk=account.id)
        .filter(Q(totp_last_timestep__isnull=True) | Q(totp_last_timestep__lt=step))
        .update(totp_last_timestep=step)
    )
    if not consumed:
        return False
    account.totp_last_timestep = step
    return True


def totp_provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(  # pyright: ignore[reportUnknownMemberType]
        name=username,
        issuer_name=webauthn_rp_name(),
    )


def totp_qr_data_uri(provisioning_uri: str) -> str:
    image = qrcode.make(provisioning_uri, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def store_totp_setup_secret(
    request: HttpRequest,
    account: LocalAdminAccount,
    secret: str,
) -> str:
    nonce = token_urlsafe(32)
    request.session[TOTP_SETUP_SESSION_KEY] = {
        "account_id": account.id,
        "issued_at": time.time(),
        "nonce": nonce,
        "secret": secret,
        "session_version": account.session_version,
    }
    return nonce


def totp_setup_secret(
    request: HttpRequest,
    account: LocalAdminAccount,
    *,
    nonce: str | None = None,
) -> str:
    payload = session_mapping(request.session.get(TOTP_SETUP_SESSION_KEY))
    if payload is None:
        return ""
    secret = payload.get("secret")
    issued_at = payload.get("issued_at")
    stored_nonce = payload.get("nonce")
    if (
        not isinstance(secret, str)
        or not isinstance(issued_at, (int, float))
        or not isinstance(stored_nonce, str)
        or payload.get("account_id") != account.id
        or payload.get("session_version") != account.session_version
        or (nonce is not None and not compare_digest(stored_nonce, nonce))
    ):
        clear_totp_setup_secret(request)
        return ""
    if time.time() - float(issued_at) > TOTP_SETUP_TTL_SECONDS:
        clear_totp_setup_secret(request)
        return ""
    return secret


def totp_setup_nonce(request: HttpRequest, account: LocalAdminAccount) -> str:
    if totp_setup_secret(request, account) == "":
        return ""
    payload = session_mapping(request.session.get(TOTP_SETUP_SESSION_KEY))
    nonce = payload.get("nonce") if payload is not None else None
    return nonce if isinstance(nonce, str) else ""


def clear_totp_setup_secret(request: HttpRequest) -> None:
    request.session.pop(TOTP_SETUP_SESSION_KEY, None)
