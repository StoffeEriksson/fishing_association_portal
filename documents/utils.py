import hashlib
from django.utils.html import strip_tags
from .models import DocumentActivity


def log_document_activity(document, user, action, message=""):
    DocumentActivity.objects.create(
        document=document,
        user=user,
        action=action,
        message=message,
    )


def build_document_hash(document):
    """
    Bygger en SHA-256-hash av dokumentets centrala innehåll.
    Om titel, kategori eller innehåll ändras efter finalisering
    så kommer hash-värdet att ändras.
    """
    content_text = strip_tags(document.content or "").strip()

    raw_value = "||".join([
        str(document.org_id or ""),
        str(document.title or ""),
        str(document.category or ""),
        content_text,
    ])

    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()
