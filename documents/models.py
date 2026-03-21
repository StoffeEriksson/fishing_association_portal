from django.conf import settings
from django.db import models

from core.tenancy import OrgModel


class DocumentCategory(models.TextChoices):
    MEETING = "meeting", "Stämmoprotokoll"
    PROTOCOL = "protocol", "Protokoll"
    BYLAWS = "bylaws", "Stadgar"
    NOTICE = "notice", "Kallelse"
    MOTION = "motion", "Motion"
    DECISION = "decision", "Beslut"
    OTHER = "other", "Övrigt"


class DocumentSourceType(models.TextChoices):
    UPLOADED = "uploaded", "Uppladdat"
    TEMPLATE = "template", "Mallbaserat"


class DocumentTemplate(models.Model):
    name = models.CharField(max_length=255)
    category = models.CharField(
        max_length=30,
        choices=DocumentCategory.choices,
        default=DocumentCategory.OTHER,
    )
    content = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Document(OrgModel):
    title = models.CharField(max_length=255)
    category = models.CharField(
        max_length=30,
        choices=DocumentCategory.choices,
        default=DocumentCategory.OTHER,
    )
    description = models.TextField(blank=True)

    source_type = models.CharField(
        max_length=20,
        choices=DocumentSourceType.choices,
        default=DocumentSourceType.UPLOADED,
    )
    content = models.TextField(blank=True)
    template = models.ForeignKey(
        "DocumentTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_documents",
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title

    @property
    def current_version(self):
        return self.versions.order_by("-version_number").first()


class DocumentVersion(models.Model):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    file = models.FileField(upload_to="documents/%Y/%m/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_versions",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-version_number"]
        unique_together = ("document", "version_number")

    def __str__(self):
        return f"{self.document.title} v{self.version_number}"


class DocumentActivity(models.Model):
    ACTION_CHOICES = [
        ("created", "Skapad"),
        ("version_added", "Ny version"),
        ("updated", "Uppdaterad"),
        ("deleted", "Borttagen"),
        ("restored", "Återställd"),
    ]

    document = models.ForeignKey(
        "Document",
        on_delete=models.CASCADE,
        related_name="activities",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.document} - {self.action} - {self.created_at}"
