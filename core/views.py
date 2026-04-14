from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from .services import audit_log

@login_required
def home(request):
    # Om du i framtiden vill hantera "ingen org", gör det här.
    org = getattr(request, "org", None)

    if org is None:
        return redirect("account_login")

    audit_log(
        request,
        action="VIEW",
        entity="Home",
        entity_id=str(request.org.id),
        message="Redirect to portal dashboard",
    )
    return redirect("portal:dashboard")
