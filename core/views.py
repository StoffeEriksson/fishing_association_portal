from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from .services import audit_log

@login_required
def home(request):
    # Om du i framtiden vill hantera "ingen org", gör det här.
    if not request.org:
        # Ex: redirecta till en sida där man väljer/skapar org
        return redirect("account_login")  # eller en egen onboarding-sida

    audit_log(
        request,
        action="VIEW",
        entity="Home",
        entity_id=str(request.org.id),
        message="Redirect to portal dashboard",
    )
    return redirect("portal:dashboard")
