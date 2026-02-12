from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from .services import audit_log


from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from .services import audit_log


@login_required
def dashboard(request):
    if not request.org:
        return HttpResponse("Ingen aktiv organisation kopplad till användaren ännu.")

    print("Dashboard accessed, org:", request.org)

    audit_log(
        request,
        action="VIEW",
        entity="Dashboard",
        entity_id=str(request.org.id),
        message="Visited dashboard",
    )

    return HttpResponse(f"Aktiv organisation: {request.org.name} (id={request.org.id})")
