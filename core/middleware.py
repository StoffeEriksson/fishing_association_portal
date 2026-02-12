from .models import Membership, Organization

ACTIVE_ORG_SESSION_KEY = "active_org_id"


class OrganizationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.org = None

        if request.user.is_authenticated:
            org_id = request.session.get(ACTIVE_ORG_SESSION_KEY)

            if org_id:
                request.org = Organization.objects.filter(id=org_id, is_active=True).first()

            if request.org is None:
                membership = (
                    Membership.objects
                    .select_related("organization")
                    .filter(user=request.user, is_active=True, organization__is_active=True)
                    .order_by("organization__name")
                    .first()
                )
                if membership:
                    request.org = membership.organization
                    request.session[ACTIVE_ORG_SESSION_KEY] = request.org.id

        return self.get_response(request)
