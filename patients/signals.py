import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Patient
from .sms import send_register_sms

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Patient)
def send_register_sms_after_patient_created(sender, instance, created, **kwargs):
    """Send the Kavenegar register template after a new patient is committed."""

    if not created:
        return

    def _send_sms():
        try:
            # اصلاح نام فیلدها مطابق با مدل Patient
            name = f"{instance.first_name}_{instance.last_name}" # وب‌سرویس کاوه نگار معمولاً در توکن‌ها فاصله (Space) قبول نمی‌کند، ترجیحاً از Underscore استفاده کنید.
            send_register_sms(instance.mobile, name)
        except Exception:
            logger.exception(
                "Failed to send Kavenegar register SMS to patient %s.", instance.pk
            )

    transaction.on_commit(_send_sms)
