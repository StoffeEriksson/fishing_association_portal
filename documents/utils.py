from .models import DocumentActivity


def log_document_activity(document, user, action, message=""):
    DocumentActivity.objects.create(
        document=document,
        user=user,
        action=action,
        message=message,
    )
