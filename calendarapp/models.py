from django.conf import settings
from django.db import models

from core.tenancy import OrgModel


class CalendarEventType(models.TextChoices):
    MEETING = "meeting", "Möte"
    ANNUAL_MEETING = "annual_meeting", "Årsmöte"
    DEADLINE = "deadline", "Deadline"
    REMINDER = "reminder", "Påminnelse"
    OTHER = "other", "Övrigt"


class CalendarEvent(OrgModel):
    meeting = models.ForeignKey(
        "governance.Meeting",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calendar_events",
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    event_type = models.CharField(
        max_length=30,
        choices=CalendarEventType.choices,
        default=CalendarEventType.OTHER,
    )

    start_at = models.DateTimeField()
    end_at = models.DateTimeField(null=True, blank=True)

    location = models.CharField(max_length=255, blank=True)
    is_all_day = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calendar_events_created",
    )

    class Meta:
        ordering = ["start_at", "title"]

    def __str__(self):
        return self.title
