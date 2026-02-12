from django.db import models


class OrgQuerySet(models.QuerySet):
    def for_org(self, org):
        if org is None:
            return self.none()
        return self.filter(org=org)


class OrgManager(models.Manager):
    def get_queryset(self):
        return OrgQuerySet(self.model, using=self._db)

    def for_org(self, org):
        return self.get_queryset().for_org(org)


class OrgModel(models.Model):
    """
    Bas för alla tenant-modeller. Alla rader tillhör exakt en organization.
    """
    org = models.ForeignKey("core.Organization", on_delete=models.PROTECT, related_name="%(class)ss")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrgManager()

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=["org"]),
        ]
