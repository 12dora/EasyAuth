from __future__ import annotations

from typing import Annotated, ClassVar, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

type TargetType = Literal["authorization_group", "permission"]
type ApproverUserid = Annotated[str, Field(min_length=1)]

APPROVERS_REQUIRED_CODE: Final = "approvers_required"
APPROVERS_REQUIRED_MESSAGE: Final = "approver_userids or approver_value is required."
TARGET_CONFLICT_CODE: Final = "target_conflict"
TARGET_CONFLICT_MESSAGE: Final = "target_key and role_key cannot both be set."
TARGET_KEY_REQUIRED_CODE: Final = "target_key_required"
TARGET_KEY_REQUIRED_MESSAGE: Final = "target_key is required."
TARGET_REQUIRED_CODE: Final = "target_required"
TARGET_REQUIRED_MESSAGE: Final = "target_type/target_key or role_key is required."
LEGACY_TARGET_REQUIRED_MESSAGE: Final = "target_key or role_key is required."
TARGET_TYPE_REQUIRED_CODE: Final = "target_type_required"
TARGET_TYPE_REQUIRED_MESSAGE: Final = "target_type is required."


class ApprovalRuleCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    target_type: TargetType | None = None
    target_key: str | None = Field(default=None, min_length=1)
    role_key: str | None = Field(default=None, min_length=1)
    approver_type: Literal["dingtalk_userids"] = "dingtalk_userids"
    approver_value: tuple[ApproverUserid, ...] | None = Field(default=None, min_length=1)
    approver_userids: tuple[ApproverUserid, ...] | None = Field(default=None, min_length=1)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        _validate_create_target(self.target_type, self.target_key, self.role_key)
        _validate_approvers(self.approver_value, self.approver_userids)
        return self


class ApprovalRulePatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    target_type: TargetType | None = None
    target_key: str | None = Field(default=None, min_length=1)
    role_key: str | None = Field(default=None, min_length=1)
    approver_type: Literal["dingtalk_userids"] | None = None
    approver_value: tuple[ApproverUserid, ...] | None = Field(default=None, min_length=1)
    approver_userids: tuple[ApproverUserid, ...] | None = Field(default=None, min_length=1)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        _validate_patch_target(self.target_type, self.target_key, self.role_key)
        return self


def create_target_type(payload: ApprovalRuleCreatePayload) -> TargetType:
    if payload.target_type is not None:
        return payload.target_type
    return "authorization_group"


def create_target_key(payload: ApprovalRuleCreatePayload) -> str:
    if payload.target_key is not None:
        return payload.target_key
    role_key = payload.role_key
    if role_key is None:
        raise PydanticCustomError(TARGET_REQUIRED_CODE, LEGACY_TARGET_REQUIRED_MESSAGE)
    return role_key


def patch_has_target(payload: ApprovalRulePatchPayload) -> bool:
    return (
        payload.target_type is not None
        or payload.target_key is not None
        or payload.role_key is not None
    )


def patch_target_type(payload: ApprovalRulePatchPayload) -> TargetType:
    if payload.target_type is not None:
        return payload.target_type
    return "authorization_group"


def patch_target_key(payload: ApprovalRulePatchPayload) -> str:
    if payload.target_key is not None:
        return payload.target_key
    role_key = payload.role_key
    if role_key is None:
        raise PydanticCustomError(TARGET_REQUIRED_CODE, LEGACY_TARGET_REQUIRED_MESSAGE)
    return role_key


def payload_approvers(
    payload: ApprovalRuleCreatePayload | ApprovalRulePatchPayload,
) -> tuple[str, ...] | None:
    if payload.approver_userids is not None:
        return payload.approver_userids
    return payload.approver_value


def patch_has_updates(payload: ApprovalRulePatchPayload) -> bool:
    return (
        patch_has_target(payload)
        or payload.approver_type is not None
        or payload.approver_value is not None
        or payload.approver_userids is not None
        or payload.is_active is not None
    )


def _validate_create_target(
    target_type: TargetType | None,
    target_key: str | None,
    role_key: str | None,
) -> None:
    if target_type is None and target_key is None and role_key is None:
        raise PydanticCustomError(TARGET_REQUIRED_CODE, TARGET_REQUIRED_MESSAGE)
    if target_type is not None and target_key is None:
        raise PydanticCustomError(TARGET_KEY_REQUIRED_CODE, TARGET_KEY_REQUIRED_MESSAGE)
    if target_type is None and target_key is not None:
        raise PydanticCustomError(TARGET_TYPE_REQUIRED_CODE, TARGET_TYPE_REQUIRED_MESSAGE)


def _validate_patch_target(
    target_type: TargetType | None,
    target_key: str | None,
    role_key: str | None,
) -> None:
    if target_type is not None and target_key is None:
        raise PydanticCustomError(TARGET_KEY_REQUIRED_CODE, TARGET_KEY_REQUIRED_MESSAGE)
    if target_type is None and target_key is not None:
        raise PydanticCustomError(TARGET_TYPE_REQUIRED_CODE, TARGET_TYPE_REQUIRED_MESSAGE)
    if target_type is not None and role_key is not None:
        raise PydanticCustomError(TARGET_CONFLICT_CODE, TARGET_CONFLICT_MESSAGE)


def _validate_approvers(
    approver_value: tuple[str, ...] | None,
    approver_userids: tuple[str, ...] | None,
) -> None:
    if approver_value is None and approver_userids is None:
        raise PydanticCustomError(APPROVERS_REQUIRED_CODE, APPROVERS_REQUIRED_MESSAGE)
