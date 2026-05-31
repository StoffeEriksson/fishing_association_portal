from core.tenancy import OrgManager, OrgQuerySet


class FisheriesEntityQuerySet(OrgQuerySet):
    def not_trashed(self):
        return self.filter(deleted_at__isnull=True)

    def trashed_only(self):
        return self.filter(deleted_at__isnull=False)


class FisheriesEntityManager(OrgManager):
    def get_queryset(self):
        return FisheriesEntityQuerySet(self.model, using=self._db)
