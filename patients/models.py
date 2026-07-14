from django.db import models


class Patient(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    mobile = models.CharField(max_length=11, unique=True)
    national_code = models.CharField(max_length=10, unique=True, null=True, blank=True)
    done_sms_sent = models.BooleanField(default=False, verbose_name="پیامک انجام شد")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.mobile}"


class SMSMessageLog(models.Model):
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = (
        (STATUS_SUCCESS, "موفق"),
        (STATUS_FAILED, "ناموفق"),
    )

    patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_logs",
        verbose_name="بیمار",
    )
    mobile = models.CharField(max_length=11, verbose_name="شماره موبایل")
    template = models.CharField(max_length=100, verbose_name="تمپلت")
    token = models.CharField(max_length=255, verbose_name="توکن ارسال‌شده")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, verbose_name="وضعیت"
    )
    response = models.TextField(blank=True, verbose_name="پاسخ سرویس")
    error = models.TextField(blank=True, verbose_name="خطا")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="زمان ارسال")

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "لاگ پیامک"
        verbose_name_plural = "لاگ‌های پیامک"

    def __str__(self):
        return f"{self.patient} - {self.template} - {self.get_status_display()}"

class VisitEvent(models.Model):
    EVENT_PAGE_VIEW = "page_view"
    EVENT_FORM_VIEW = "form_view"
    EVENT_HERO_CTA_CLICK = "hero_cta_click"
    EVENT_STICKY_CTA_CLICK = "sticky_cta_click"
    EVENT_SECTION_VIEW = "section_view"
    EVENT_FORM_START = "form_start"
    EVENT_FIELD_COMPLETE = "field_complete"
    EVENT_SCROLL_DEPTH = "scroll_depth"
    EVENT_FORM_SUBMIT_ATTEMPT = "form_submit_attempt"
    EVENT_FORM_SUBMIT_SUCCESS = "form_submit_success"
    EVENT_FORM_SUBMIT_INVALID = "form_submit_invalid"
    EVENT_FORM_SUBMIT_ERROR = "form_submit_error"
    EVENT_APK_DOWNLOAD = "apk_download"

    EVENT_TYPE_CHOICES = (
        (EVENT_PAGE_VIEW, "بازدید صفحه"),
        (EVENT_FORM_VIEW, "مشاهده فرم"),
        (EVENT_HERO_CTA_CLICK, "کلیک CTA اصلی"),
        (EVENT_STICKY_CTA_CLICK, "کلیک CTA چسبان"),
        (EVENT_SECTION_VIEW, "مشاهده بخش صفحه"),
        (EVENT_FORM_START, "شروع تکمیل فرم"),
        (EVENT_FIELD_COMPLETE, "تکمیل فیلد فرم"),
        (EVENT_SCROLL_DEPTH, "عمق اسکرول"),
        (EVENT_FORM_SUBMIT_ATTEMPT, "تلاش ثبت‌نام"),
        (EVENT_FORM_SUBMIT_SUCCESS, "ثبت‌نام موفق"),
        (EVENT_FORM_SUBMIT_INVALID, "ثبت‌نام نامعتبر"),
        (EVENT_FORM_SUBMIT_ERROR, "خطای ثبت‌نام"),
        (EVENT_APK_DOWNLOAD, "دانلود اپلیکیشن"),
    )

    visitor_id = models.UUIDField(db_index=True, verbose_name="شناسه بازدیدکننده")
    session_key = models.CharField(max_length=64, blank=True, db_index=True, verbose_name="شناسه نشست")
    event_type = models.CharField(max_length=32, choices=EVENT_TYPE_CHOICES, db_index=True, verbose_name="نوع رویداد")
    method = models.CharField(max_length=10, verbose_name="روش درخواست")
    path = models.CharField(max_length=255, db_index=True, verbose_name="مسیر")
    query_string = models.TextField(blank=True, verbose_name="کوئری")
    referrer = models.TextField(blank=True, verbose_name="ارجاع‌دهنده")
    user_agent = models.TextField(blank=True, verbose_name="مرورگر/دستگاه")
    ip_hash = models.CharField(max_length=128, blank=True, db_index=True, verbose_name="هش آی‌پی")
    masked_ip = models.CharField(max_length=64, blank=True, db_index=True, verbose_name="آی‌پی ماسک‌شده")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="آی‌پی کامل")
    device_type = models.CharField(max_length=32, blank=True, db_index=True, verbose_name="نوع دستگاه")
    browser = models.CharField(max_length=80, blank=True, verbose_name="مرورگر")
    os = models.CharField(max_length=80, blank=True, verbose_name="سیستم‌عامل")
    is_bot = models.BooleanField(default=False, db_index=True, verbose_name="ربات")
    utm_source = models.CharField(max_length=120, blank=True, db_index=True, verbose_name="منبع UTM")
    utm_medium = models.CharField(max_length=120, blank=True, verbose_name="مدیوم UTM")
    utm_campaign = models.CharField(max_length=120, blank=True, db_index=True, verbose_name="کمپین UTM")
    utm_content = models.CharField(max_length=120, blank=True, verbose_name="محتوای UTM")
    utm_term = models.CharField(max_length=120, blank=True, verbose_name="کلمه UTM")
    status_code = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="وضعیت پاسخ")
    patient = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.SET_NULL, related_name="visit_events", verbose_name="بیمار")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="فراداده")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="زمان ایجاد")

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "رویداد بازدید"
        verbose_name_plural = "رویدادهای بازدید"
        indexes = []

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.path}"


class VisitReport(VisitEvent):
    class Meta:
        proxy = True
        verbose_name = "گزارش بازدید سایت"
        verbose_name_plural = "گزارش بازدید سایت"
