from django.db import migrations, models

from easyauth.accounts.pinyin import name_pinyin_fields

_BACKFILL_BATCH_SIZE = 500


def backfill_name_pinyin(apps, _schema_editor):
    user_model = apps.get_model("accounts", "UserMirror")
    batch = []
    for user in user_model.objects.iterator(chunk_size=_BACKFILL_BATCH_SIZE):
        pinyin, initials = name_pinyin_fields(user.name)
        user.name_pinyin = pinyin
        user.name_pinyin_initials = initials
        batch.append(user)
        if len(batch) >= _BACKFILL_BATCH_SIZE:
            _ = user_model.objects.bulk_update(batch, ["name_pinyin", "name_pinyin_initials"])
            batch = []
    if batch:
        _ = user_model.objects.bulk_update(batch, ["name_pinyin", "name_pinyin_initials"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0018_oidcsessionbinding"),
    ]

    operations = [
        migrations.AddField(
            model_name="usermirror",
            name="name_pinyin",
            field=models.CharField(blank=True, db_index=True, default="", max_length=768),
        ),
        migrations.AddField(
            model_name="usermirror",
            name="name_pinyin_initials",
            field=models.CharField(blank=True, db_index=True, default="", max_length=128),
        ),
        migrations.RunPython(backfill_name_pinyin, migrations.RunPython.noop),
    ]
