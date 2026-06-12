from __future__ import annotations


def role_access_policy_max_duration_clean_errors(
    *,
    is_high_risk: bool,
    max_grant_duration_days: int | None,
) -> dict[str, str]:
    if is_high_risk and max_grant_duration_days is None:
        return {"max_grant_duration_days": "High-risk roles need a max duration."}
    if not is_high_risk and max_grant_duration_days is not None:
        return {"max_grant_duration_days": "Only high-risk roles may set max duration."}
    return {}
