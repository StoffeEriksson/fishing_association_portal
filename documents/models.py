from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.tenancy import OrgModel


class DocumentCategory(models.TextChoices):
    PROTOCOL = "protocol", "Protokoll"
    BYLAWS = "bylaws", "Stadgar"
    NOTICE = "notice", "Kallelse"
    MOTION = "motion", "Motion"
    DECISION = "decision", "Beslut"
    OTHER = "other", "Övrigt"


class DocumentSourceType(models.TextChoices):
    UPLOADED = "uploaded", "Uppladdat"
    TEMPLATE = "template", "Mallbaserat"


class DocumentWorkflowStatus(models.TextChoices):
    DRAFT = "draft", "Utkast"
    LOCKED_FOR_REVIEW = "locked_for_review", "Låst för justering"
    UNDER_REVIEW = "under_review", "Under justering"
    APPROVED = "approved", "Godkänt"
    FINALIZED = "finalized", "Avslutat"


class DocumentApprovalStatus(models.TextChoices):
    PENDING = "pending", "Väntar"
    APPROVED = "approved", "Godkänd"
    CHANGES_REQUESTED = "changes_requested", "Ändringar begärda"


class DocumentSignatureRole(models.TextChoices):
    CHAIR = "chair", "Ordförande"
    SECRETARY = "secretary", "Sekreterare"
    ADJUSTER = "adjuster", "Justerare"


class DocumentSignatureStatus(models.TextChoices):
    PENDING = "pending", "Väntar"
    SIGNED = "signed", "Signerad"


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


class DocumentFolderType(models.TextChoices):
    ARCHIVE_ROOT = "archive_root", "Arkiv"
    YEAR = "year", "År"
    MONTH = "month", "Månad"
    MEETING_GROUP = "meeting_group", "Möteskategori"
    STATIC = "static", "Systemmapp"
    CUSTOM = "custom", "Anpassad"


class DocumentFolder(OrgModel):
    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_folders_created",
    )
    is_system_folder = models.BooleanField(default=False)
    folder_type = models.CharField(
        max_length=40,
        choices=DocumentFolderType.choices,
        default=DocumentFolderType.CUSTOM,
    )
    system_key = models.CharField(max_length=160, blank=True, db_index=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    month = models.PositiveSmallIntegerField(null=True, blank=True)
    meeting_type = models.CharField(max_length=20, blank=True)
    related_meeting = models.ForeignKey(
        "governance.Meeting",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_folders",
    )

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["org", "parent"]),
            models.Index(fields=["org", "folder_type"]),
            models.Index(fields=["org", "system_key"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "system_key"],
                condition=Q(is_system_folder=True),
                name="uniq_document_folder_system_key_per_org",
            ),
            models.UniqueConstraint(
                fields=["org", "parent", "name"],
                condition=Q(is_system_folder=False),
                name="uniq_document_folder_name_per_parent_org",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        if self.parent_id and self.parent.org_id != self.org_id:
            raise ValidationError({"parent": "Överordnad mapp måste tillhöra samma organisation."})

        if self.related_meeting_id and self.related_meeting.org_id != self.org_id:
            raise ValidationError(
                {"related_meeting": "Kopplat möte måste tillhöra samma organisation."}
            )


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

    meeting = models.ForeignKey(
        "governance.Meeting",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )

    workflow_status = models.CharField(
        max_length=30,
        choices=DocumentWorkflowStatus.choices,
        default=DocumentWorkflowStatus.DRAFT,
    )

    locked_at = models.DateTimeField(null=True, blank=True)

    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="locked_documents",
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
    is_archived = models.BooleanField(default=False)
    document_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_documents",
    )
    folder = models.ForeignKey(
        "DocumentFolder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    folder_auto_assigned = models.BooleanField(default=False)

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


class DocumentApproval(models.Model):
    document = models.ForeignKey(
        "Document",
        on_delete=models.CASCADE,
        related_name="approvals",
    )

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document_approvals",
    )

    status = models.CharField(
        max_length=30,
        choices=DocumentApprovalStatus.choices,
        default=DocumentApprovalStatus.PENDING,
    )

    comment = models.TextField(blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("document", "reviewer")
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.document.title} - {self.reviewer} - {self.get_status_display()}"


class DocumentSignature(models.Model):
    document = models.ForeignKey(
        "Document",
        on_delete=models.CASCADE,
        related_name="signatures",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document_signatures",
    )

    role = models.CharField(
        max_length=20,
        choices=DocumentSignatureRole.choices,
    )

    status = models.CharField(
        max_length=20,
        choices=DocumentSignatureStatus.choices,
        default=DocumentSignatureStatus.PENDING,
    )

    signed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("document", "user", "role")
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.document.title} - {self.user} - {self.get_role_display()}"