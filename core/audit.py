from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """
    Minimal auditlogg. Vi kan bygga på senare (diffar, källor, risknivåer, AI-logg etc).
    """
    org = models.ForeignKey("core.Organization", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    action = models.CharField(max_length=50)  # ex: "CREATE", "UPDATE", "DELETE", "LOGIN", "EXPORT"
    entity = models.CharField(max_length=100)  # ex: "FishingRight", "Document"
    entity_id = models.CharField(max_length=64, blank=True)  # str(id) eller UUID
    message = models.TextField(blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["org", "created_at"]),
            models.Index(fields=["entity", "entity_id"]),
        ]

    def __str__(self):
        return f"{self.created_at} {self.org} {self.action} {self.entity}#{self.entity_id}"
