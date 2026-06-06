from __future__ import annotations

from django.http import JsonResponse

from easyauth.admin_console.catalog_write_common import save_model
from easyauth.applications.models import PermissionGroup


def update_descendant_depths(group: PermissionGroup) -> JsonResponse | None:
    children = PermissionGroup.objects.filter(parent=group).order_by("id")
    for child in children:
        child.depth = group.depth + 1
        match save_model(child):
            case None:
                pass
            case JsonResponse() as response:
                return response
        match update_descendant_depths(child):
            case None:
                pass
            case JsonResponse() as response:
                return response
    return None
