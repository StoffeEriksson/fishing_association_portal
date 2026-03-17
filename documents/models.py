from django.conf import settings
from django.db import models

from core.tenancy import OrgModel


class DocumentCategory(models.TextChoices):
    PROTOCOL = "protocol", "Protokoll"
    BYLAWS = "bylaws", "Stadgar"
    NOTICE = "notice", "Kallelse"
    MOTION = "motion", "Motion"
    DECISION = "decision", "Beslut"
    OTHER = "other", "Övrigt"


class Document(OrgModel):
    title = models.CharField(max_length=255)
    category = models.CharField(
        max_length=30,
        choices=DocumentCategory.choices,
        default=DocumentCategory.OTHER,
    )
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="documents/%Y/%m/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_documents",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.title