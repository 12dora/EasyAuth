from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final

from django.db import IntegrityError, transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console.api_payloads import list_payload
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.teams.models import (
    TEAM_MEMBER_ROLE_LEADER,
    TEAM_MEMBER_ROLE_VALUES,
    Team,
    TeamMember,
)

if TYPE_CHECKING:
    from easyauth.applications.ownership import ConsoleActor

type SuperuserResult = ConsoleActor | JsonResponse
type TeamLookupResult = Team | JsonResponse
type MemberLookupResult = TeamMember | JsonResponse

INVALID_ROLE_MESSAGE: Final = "角色必须为 leader 或 member。"
TEAMS_FORBIDDEN_MESSAGE: Final = "只有控制台超级管理员可以管理团队。"


class TeamCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)


class TeamPatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class TeamMemberAddPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    user_id: str = Field(min_length=1, max_length=128)
    role: str = Field(max_length=16)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in TEAM_MEMBER_ROLE_VALUES:
            raise ValueError(INVALID_ROLE_MESSAGE)
        return value


class TeamMemberPatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    role: str = Field(max_length=16)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in TEAM_MEMBER_ROLE_VALUES:
            raise ValueError(INVALID_ROLE_MESSAGE)
        return value


def console_teams(request: HttpRequest) -> JsonResponse:
    # 团队成员关系是跨 App 的组织架构 oracle, 且直接决定 MANAGED_USERS
    # 可见范围: 读写都收紧到控制台超级管理员。
    match _require_superuser(request):
        case JsonResponse() as response:
            return response
        case actor:
            pass
    if request.method == "GET":
        teams = list(Team.objects.order_by("name"))
        members_by_team: dict[int, list[TeamMember]] = {}
        for member in TeamMember.objects.select_related("user").filter(team__in=teams):
            members_by_team.setdefault(member.team_id, []).append(member)
        return json_response(
            list_payload(
                [
                    _team_item_from_members(team, members_by_team.get(team.id, []))
                    for team in teams
                ],
            ),
        )
    if request.method == "POST":
        return _create_team(request, actor)
    return method_not_allowed_response()


def console_team_detail(request: HttpRequest, team_id: int) -> JsonResponse:
    match _require_superuser(request):
        case JsonResponse() as response:
            return response
        case actor:
            pass
    team = _team_or_404(team_id)
    if isinstance(team, JsonResponse):
        return team
    if request.method == "GET":
        return json_response(_team_detail_payload(team))
    if request.method == "PATCH":
        return _patch_team(request, team, actor)
    return method_not_allowed_response()


def console_team_members(request: HttpRequest, team_id: int) -> JsonResponse:
    match _require_superuser(request):
        case JsonResponse() as response:
            return response
        case actor:
            pass
    team = _team_or_404(team_id)
    if isinstance(team, JsonResponse):
        return team
    if request.method != "POST":
        return method_not_allowed_response()
    return _add_member(request, team, actor)


def console_team_member_detail(
    request: HttpRequest,
    team_id: int,
    member_id: int,
) -> JsonResponse:
    match _require_superuser(request):
        case JsonResponse() as response:
            return response
        case actor:
            pass
    team = _team_or_404(team_id)
    if isinstance(team, JsonResponse):
        return team
    member = _member_or_404(team, member_id)
    if isinstance(member, JsonResponse):
        return member
    if request.method == "PATCH":
        return _patch_member(request, team, member, actor)
    if request.method == "DELETE":
        return _remove_member(team, member, actor)
    return method_not_allowed_response()


def _create_team(request: HttpRequest, actor: ConsoleActor) -> JsonResponse:
    try:
        payload = TeamCreatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("团队参数无效。", {"errors": str(exc)})
    if Team.objects.filter(name=payload.name).exists():
        return _validation_error("同名团队已存在。")
    team = Team.objects.create(
        name=payload.name,
        description=payload.description,
        created_by=actor.user_id,
    )
    _record_team_event(actor=actor, team=team, action="team_created")
    return json_response(_team_detail_payload(team), status=HTTPStatus.CREATED)


def _patch_team(request: HttpRequest, team: Team, actor: ConsoleActor) -> JsonResponse:
    try:
        payload = TeamPatchPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("团队参数无效。", {"errors": str(exc)})
    if payload.name is not None and payload.name != team.name:
        if Team.objects.filter(name=payload.name).exclude(id=team.id).exists():
            return _validation_error("同名团队已存在。")
        team.name = payload.name
    if payload.description is not None:
        team.description = payload.description
    if payload.is_active is not None:
        team.is_active = payload.is_active
    team.save()
    _record_team_event(
        actor=actor,
        team=team,
        action="team_updated",
        extra={"is_active": team.is_active},
    )
    return json_response(_team_detail_payload(team))


def _add_member(request: HttpRequest, team: Team, actor: ConsoleActor) -> JsonResponse:
    try:
        payload = TeamMemberAddPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("成员参数无效。", {"errors": str(exc)})
    user = UserMirror.objects.filter(
        authentik_user_id=payload.user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if user is None:
        return _validation_error("用户不存在或已停用。")
    try:
        with transaction.atomic():
            member = TeamMember.objects.create(
                team=team,
                user=user,
                role=payload.role,
                added_by=actor.user_id,
            )
    except IntegrityError:
        return _validation_error("该用户已在团队中。")
    _record_member_event(
        actor=actor,
        team=team,
        member=member,
        action="team_member_added",
    )
    return json_response(_team_detail_payload(team), status=HTTPStatus.CREATED)


def _patch_member(
    request: HttpRequest,
    team: Team,
    member: TeamMember,
    actor: ConsoleActor,
) -> JsonResponse:
    try:
        payload = TeamMemberPatchPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("成员参数无效。", {"errors": str(exc)})
    member.role = payload.role
    member.save()
    _record_member_event(
        actor=actor,
        team=team,
        member=member,
        action="team_member_role_updated",
    )
    return json_response(_team_detail_payload(team))


def _remove_member(team: Team, member: TeamMember, actor: ConsoleActor) -> JsonResponse:
    _record_member_event(
        actor=actor,
        team=team,
        member=member,
        action="team_member_removed",
    )
    _ = member.delete()
    return json_response(_team_detail_payload(team))


def _require_superuser(request: HttpRequest) -> SuperuserResult:
    match require_console_actor(request):
        case JsonResponse() as response:
            return response
        case actor:
            pass
    if not actor.is_superuser:
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            TEAMS_FORBIDDEN_MESSAGE,
            status=HTTPStatus.FORBIDDEN,
        )
    return actor


def _team_or_404(team_id: int) -> TeamLookupResult:
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            "团队不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    return team


def _member_or_404(team: Team, member_id: int) -> MemberLookupResult:
    member = TeamMember.objects.select_related("user").filter(team=team, id=member_id).first()
    if member is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            "团队成员不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    return member


def _team_detail_payload(team: Team) -> dict[str, JsonValue]:
    members = list(
        TeamMember.objects.select_related("user")
        .filter(team=team)
        .order_by("role", "user__name", "user__authentik_user_id"),
    )
    item = _team_item_from_members(team, members)
    members_payload: list[JsonValue] = [_member_item(member) for member in members]
    item["members"] = members_payload
    return {"team": item}


def _team_item_from_members(team: Team, members: list[TeamMember]) -> dict[str, JsonValue]:
    leaders: list[JsonValue] = [
        _member_user_summary(member)
        for member in members
        if member.role == TEAM_MEMBER_ROLE_LEADER
    ]
    return {
        "id": team.id,
        "name": team.name,
        "description": team.description,
        "is_active": team.is_active,
        "leaders": leaders,
        "member_count": len(members),
        "created_at": team.created_at.isoformat(),
        "updated_at": team.updated_at.isoformat(),
    }


def _member_item(member: TeamMember) -> dict[str, JsonValue]:
    return {
        "id": member.id,
        "user_id": member.user.authentik_user_id,
        "name": member.user.name,
        "email": member.user.email,
        "department": member.user.department,
        "status": member.user.status,
        "role": member.role,
        "added_at": member.added_at.isoformat(),
    }


def _member_user_summary(member: TeamMember) -> dict[str, JsonValue]:
    return {
        "user_id": member.user.authentik_user_id,
        "name": member.user.name,
    }


def _validation_error(
    message: str,
    details: dict[str, JsonValue] | None = None,
) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.BAD_REQUEST,
    )


def _record_team_event(
    *,
    actor: ConsoleActor,
    team: Team,
    action: str,
    extra: dict[str, JsonValue] | None = None,
) -> None:
    metadata: dict[str, JsonValue] = {"team_name": team.name}
    if extra is not None:
        metadata.update(extra)
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.user_id,
            action=action,
            target_type="team",
            target_id=str(team.id),
            metadata=metadata,
        ),
    )


def _record_member_event(
    *,
    actor: ConsoleActor,
    team: Team,
    member: TeamMember,
    action: str,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.user_id,
            action=action,
            target_type="team",
            target_id=str(team.id),
            metadata={
                "team_name": team.name,
                "member_user_id": member.user.authentik_user_id,
                "role": member.role,
            },
        ),
    )
