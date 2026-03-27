from django.conf import settings
from django.db import models

from core.tenancy import OrgModel


class BoardRole(models.TextChoices):
    CHAIR = "chair", "Ordförande"
    SECRETARY = "secretary", "Sekreterare"
    TREASURER = "treasurer", "Kassör"
    MEMBER = "member", "Ledamot"
    DEPUTY = "deputy", "Suppleant"


class BoardMembership(OrgModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="board_memberships",
    )

    role = models.CharField(
        max_length=20,
        choices=BoardRole.choices,
        default=BoardRole.MEMBER,
    )

    is_active = models.BooleanField(default=True)

    can_manage_members = models.BooleanField(default=False)
    can_manage_matters = models.BooleanField(default=False)
    can_manage_documents = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("org", "user")
        ordering = ["role", "user__email"]

    def __str__(self):
        return f"{self.user} - {self.get_role_display()}"


class GovernanceActivityLog(OrgModel):
    ACTION_CHOICES = [
        ("member_created", "Styrelsemedlem skapad"),
        ("member_updated", "Styrelsemedlem uppdaterad"),
        ("member_deleted", "Styrelsemedlem borttagen"),
        ("permission_changed", "Behörighet ändrad"),
        ("login_access", "Åtkomst till governance"),
        ("matter_created", "Ärende skapat"),
        ("matter_updated", "Ärende uppdaterat"),
        ("matter_status_changed", "Ärendestatus ändrad"),
        ("meeting_created", "Stämma skapad"),
        ("meeting_updated", "Stämma uppdaterad"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="governance_activities",
    )

    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    message = models.CharField(max_length=255, blank=True)

    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="governance_targeted_activities",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} - {self.created_at:%Y-%m-%d %H:%M}"


class MatterStatus(models.TextChoices):
    RECEIVED = "received", "Inkommen"
    IN_PREPARATION = "in_preparation", "Under beredning"
    READY_FOR_PROPOSAL = "ready_for_proposal", "Klar för styrelseförslag"
    READY_FOR_MEETING = "ready_for_meeting", "Klar för stämma"
    DECIDED = "decided", "Beslutad"
    CLOSED = "closed", "Avslutad"


class MatterType(models.TextChoices):
    MOTION = "motion", "Motion"
    CASE = "case", "Ärende"
    INFORMATION = "information", "Information"


class BoardMatter(OrgModel):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    type = models.CharField(
        max_length=20,
        choices=MatterType.choices,
        default=MatterType.CASE,
    )

    status = models.CharField(
        max_length=30,
        choices=MatterStatus.choices,
        default=MatterStatus.RECEIVED,
    )

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_matters",
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_matters",
    )

    meeting = models.ForeignKey(
        "Meeting",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matters",
    )

    board_comment = models.TextField(blank=True)
    prepared_statement = models.TextField(blank=True)

    ready_for_meeting = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Meeting(OrgModel):
    MEETING_TYPE_CHOICES = [
        ("annual", "Årsstämma"),
        ("extra", "Extra stämma"),
        ("board", "Styrelsemöte"),
    ]

    title = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True)

    meeting_type = models.CharField(
        max_length=20,
        choices=MEETING_TYPE_CHOICES,
    )

    meeting_date = models.DateTimeField()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_meetings",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-meeting_date"]

    def __str__(self):
        return self.title


class MeetingMatter(models.Model):
    meeting = models.ForeignKey(
        "Meeting",
        on_delete=models.CASCADE,
        related_name="meeting_matters",
    )

    matter = models.ForeignKey(
        "BoardMatter",
        on_delete=models.CASCADE,
        related_name="meeting_links",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("meeting", "matter")
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.meeting.title} - {self.matter.title}"
