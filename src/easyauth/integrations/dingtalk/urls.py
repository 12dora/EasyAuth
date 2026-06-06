from __future__ import annotations

from django.urls import path

from easyauth.integrations.dingtalk.callbacks import dingtalk_callback

urlpatterns = [
    path("callback", dingtalk_callback, name="dingtalk-callback"),
]
