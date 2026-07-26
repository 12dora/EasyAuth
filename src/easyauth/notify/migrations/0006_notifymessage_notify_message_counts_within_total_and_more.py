from django.db import migrations, models
from django.db.models import F, Q


class NotifyStateMigrationError(RuntimeError):
    pass


def assert_notify_state_invariants(apps, _schema_editor):
    message_model = apps.get_model("notify", "NotifyMessage")
    recipient_model = apps.get_model("notify", "NotifyRecipient")
    bad_message_ids = list(
        message_model.objects.filter(
            Q(recipient_sent__gt=F("recipient_total"))
            | Q(recipient_failed__gt=F("recipient_total"))
            | Q(recipient_sent__gt=F("recipient_total") - F("recipient_failed"))
            | (
                Q(claim_token="")
                & Q(lease_expires_at__isnull=False)
            )
            | (
                ~Q(claim_token="")
                & Q(lease_expires_at__isnull=True)
            )
            | (
                Q(status__in=("completed", "partially_failed", "failed"))
                & Q(completed_at__isnull=True)
            )
            | (
                Q(status__in=("pending", "sending"))
                & Q(completed_at__isnull=False)
            )
            | (
                Q(status__in=("completed", "partially_failed", "failed"))
                & ~Q(claim_token="")
            ),
        )
        .order_by("id")
        .values_list("id", flat=True)[:20],
    )
    bad_recipient_ids = list(
        recipient_model.objects.filter(
            (
                Q(status="delivered")
                & Q(delivered_at__isnull=True)
            )
            | (
                Q(status="failed")
                & Q(error_code="")
            ),
        )
        .order_by("id")
        .values_list("id", flat=True)[:20],
    )
    if bad_message_ids or bad_recipient_ids:
        message = (
            "通知状态机约束迁移被阻断: "
            f"message_sample_ids={list(bad_message_ids)}, "
            f"recipient_sample_ids={list(bad_recipient_ids)}"
        )
        raise NotifyStateMigrationError(message)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0015_alter_usermirror_options_and_more'),
        ('applications', '0028_alter_managedscopepolicy_options_and_more'),
        ('notify', '0005_scoped_recipient_identity'),
    ]

    operations = [
        migrations.RunPython(assert_notify_state_invariants, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='notifymessage',
            constraint=models.CheckConstraint(condition=models.Q(('recipient_sent__lte', models.F('recipient_total')), ('recipient_failed__lte', models.F('recipient_total')), ('recipient_sent__lte', models.F('recipient_total') - models.F('recipient_failed'))), name='notify_message_counts_within_total'),
        ),
        migrations.AddConstraint(
            model_name='notifymessage',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('claim_token', ''), ('lease_expires_at__isnull', True)), models.Q(models.Q(('claim_token', ''), _negated=True), ('lease_expires_at__isnull', False)), _connector='OR'), name='notify_message_claim_lease_pair'),
        ),
        migrations.AddConstraint(
            model_name='notifymessage',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('claim_token', ''), ('completed_at__isnull', False), ('lease_expires_at__isnull', True), ('status__in', ('completed', 'partially_failed', 'failed'))), models.Q(('completed_at__isnull', True), ('status__in', ('pending', 'sending'))), _connector='OR'), name='notify_message_terminal_shape'),
        ),
        migrations.AddConstraint(
            model_name='notifyrecipient',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('delivered_at__isnull', False), ('status', 'delivered')), models.Q(('status', 'delivered'), _negated=True), _connector='OR'), name='notify_recipient_delivered_shape'),
        ),
        migrations.AddConstraint(
            model_name='notifyrecipient',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('status', 'failed'), _negated=True), models.Q(('status', 'failed'), models.Q(('error_code', ''), _negated=True)), _connector='OR'), name='notify_recipient_failed_error_code_shape'),
        ),
    ]
