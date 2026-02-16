from django.db import models
from core.models import Organization


class Property(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="properties")

    # Fastighetsbeteckning, t.ex. "Rätan 1:12"
    designation = models.CharField(max_length=255)

    # Om du vill: fastighets-id från register senare (Lantmäteriet etc)
    external_id = models.CharField(max_length=64, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("org", "designation")
        ordering = ["designation"]

    def __str__(self):
        return self.designation


class RightHolder(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="right_holders")

    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("org", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name


class FishingRightShare(models.Model):
    """
    Koppling: en ägare har en andel i en fastighet.
    """
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="fishing_right_shares")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="shares")
    holder = models.ForeignKey(RightHolder, on_delete=models.CASCADE, related_name="shares")

    # Andelstal: välj decimal, eftersom register ofta har bråk/decimaler
    share = models.DecimalField(max_digits=12, decimal_places=6)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("org", "property", "holder")
        ordering = ["property__designation", "holder__name"]

    def __str__(self):
        return f"{self.property} - {self.holder} ({self.share})"
