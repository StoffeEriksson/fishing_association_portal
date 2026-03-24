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
