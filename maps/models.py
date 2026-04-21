from django.db import models

from core.tenancy import OrgModel


class FishSpecies(models.Model):
    name = models.CharField(max_length=100)
    latin_name = models.CharField(max_length=150, blank=True)

    def __str__(self):
        return self.name


class MapBoundary(OrgModel):
    name = models.CharField(max_length=255)
    geojson = models.JSONField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class WaterBodyType(models.TextChoices):
    LAKE = "lake", "Sjö"
    RIVER = "river", "Vattendrag"
    OTHER = "other", "Övrigt"


class WaterBody(OrgModel):
    name = models.CharField(max_length=255)
    water_type = models.CharField(
        max_length=20,
        choices=WaterBodyType.choices,
        default=WaterBodyType.OTHER,
    )
    geojson = models.JSONField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    species = models.ManyToManyField(
        FishSpecies,
        blank=True,
        related_name="water_bodies",
    )

    def __str__(self):
        return self.name
