from .audit import AuditEvent


def get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def audit_log(request, *, action: str, entity: str, entity_id: str = "", message: str = ""):
    if not getattr(request, "org", None):
        return

    AuditEvent.objects.create(
        org=request.org,
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id else "",
        message=message,
        ip_address=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
