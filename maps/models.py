from django.db import models
from django.db.models import Q

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
    viss_ms_cd = models.CharField(
        max_length=32,
        blank=True,
        db_index=True,
        help_text="VISS MS_CD / waterpublicid",
    )
    viss_eu_cd = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="VISS EU_CD",
    )
    external_source = models.CharField(
        max_length=64,
        blank=True,
        help_text='Exempel: "viss"',
    )
    geometry_source = models.CharField(
        max_length=128,
        blank=True,
        help_text='Exempel: "viss_arcgis_layer_56"',
    )
    source_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Officiellt namn från källan",
    )
    imported_at = models.DateTimeField(null=True, blank=True)
    species = models.ManyToManyField(
        FishSpecies,
        blank=True,
        related_name="water_bodies",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["org", "viss_ms_cd"],
                condition=~Q(viss_ms_cd=""),
                name="unique_waterbody_org_viss_ms_cd",
            ),
        ]

    def __str__(self):
        return self.name
