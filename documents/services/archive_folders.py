"""
Idempotent creation of the SharePoint-like archive folder tree for documents.

This module only returns DocumentFolder instances. It does not assign documents
to folders, change workflow state, or persist document fields.
"""

from django.utils import timezone

from documents.models import Document, DocumentFolder, DocumentFolderType

ARCHIVE_ROOT_SYSTEM_KEY = "archive"

MONTH_NAMES = {
    1: "Januari",
    2: "Februari",
    3: "Mars",
    4: "April",
    5: "Maj",
    6: "Juni",
    7: "Juli",
    8: "Augusti",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "December",
}

MEETING_TYPE_LABELS = {
    "board": "Styrelsemöten",
    "annual": "Årsstämma",
    "extra": "Extra stämma",
}

MEETING_TYPE_SYSTEM_KEY_SUFFIX = {
    "board": "board",
    "annual": "annual",
    "extra": "extra",
}

FALLBACK_MEETING_TYPE = "other"
FALLBACK_MEETING_LABEL = "Övrigt"


def ensure_archive_path(document: Document) -> DocumentFolder:
    """
    Return the archive folder where *document* should eventually be placed.

    Creates missing system folders under: Arkiv → År → Månad → Möteskategori.
    Safe to call repeatedly (get_or_create). Does not modify *document*.
    """
    if document.org_id is None:
        raise ValueError("Document must belong to an organization.")

    org = document.org

    meeting = document.meeting
    if meeting is not None and meeting.org_id != org.id:
        raise ValueError("Meeting must belong to the same organization as the document.")

    if meeting is not None:
        local_dt = _local_datetime(meeting.meeting_date)
        year = local_dt.year
        month = local_dt.month
        meeting_type = meeting.meeting_type
    else:
        today = timezone.localdate()
        year = today.year
        month = today.month
        meeting_type = FALLBACK_MEETING_TYPE

    root = _get_or_create_archive_root(org)
    year_folder = _get_or_create_year_folder(org, root, year)
    month_folder = _get_or_create_month_folder(org, year_folder, year, month)
    return _get_or_create_meeting_folder(org, month_folder, year, month, meeting_type)


def _local_datetime(dt):
    """Normalize meeting_date to local wall-clock time for year/month extraction."""
    if timezone.is_aware(dt):
        return timezone.localtime(dt)
    return dt


def _get_or_create_system_folder(
    *,
    org,
    parent,
    name: str,
    system_key: str,
    folder_type: str,
    year=None,
    month=None,
    meeting_type: str = "",
) -> DocumentFolder:
    folder, _created = DocumentFolder.objects.get_or_create(
        org=org,
        system_key=system_key,
        is_system_folder=True,
        defaults={
            "name": name,
            "parent": parent,
            "folder_type": folder_type,
            "year": year,
            "month": month,
            "meeting_type": meeting_type,
            "is_system_folder": True,
        },
    )
    return folder


def _get_or_create_archive_root(org) -> DocumentFolder:
    """Top-level archive folder for the organization."""
    return _get_or_create_system_folder(
        org=org,
        parent=None,
        name="Arkiv",
        system_key=ARCHIVE_ROOT_SYSTEM_KEY,
        folder_type=DocumentFolderType.ARCHIVE_ROOT,
    )


def _get_or_create_year_folder(org, parent: DocumentFolder, year: int) -> DocumentFolder:
    """Year folder under the archive root."""
    return _get_or_create_system_folder(
        org=org,
        parent=parent,
        name=str(year),
        system_key=f"{ARCHIVE_ROOT_SYSTEM_KEY}/{year}",
        folder_type=DocumentFolderType.YEAR,
        year=year,
    )


def _get_or_create_month_folder(
    org,
    parent: DocumentFolder,
    year: int,
    month: int,
) -> DocumentFolder:
    """Month folder under a year folder (Swedish month name)."""
    month_label = MONTH_NAMES.get(month, str(month))
    month_key = f"{month:02d}"
    return _get_or_create_system_folder(
        org=org,
        parent=parent,
        name=month_label,
        system_key=f"{ARCHIVE_ROOT_SYSTEM_KEY}/{year}/{month_key}",
        folder_type=DocumentFolderType.MONTH,
        year=year,
        month=month,
    )


def _resolve_meeting_type(meeting_type: str) -> tuple[str, str, str]:
    """
    Map meeting_type to (display name, system_key suffix, stored meeting_type).

    Unknown types fall back to Övrigt / other.
    """
    suffix = MEETING_TYPE_SYSTEM_KEY_SUFFIX.get(meeting_type)
    if suffix is None:
        return FALLBACK_MEETING_LABEL, FALLBACK_MEETING_TYPE, FALLBACK_MEETING_TYPE
    return MEETING_TYPE_LABELS[meeting_type], suffix, meeting_type


def _get_or_create_meeting_folder(
    org,
    parent: DocumentFolder,
    year: int,
    month: int,
    meeting_type: str,
) -> DocumentFolder:
    """Meeting category folder under a month folder."""
    name, key_suffix, stored_type = _resolve_meeting_type(meeting_type)
    month_key = f"{month:02d}"
    return _get_or_create_system_folder(
        org=org,
        parent=parent,
        name=name,
        system_key=f"{ARCHIVE_ROOT_SYSTEM_KEY}/{year}/{month_key}/{key_suffix}",
        folder_type=DocumentFolderType.MEETING_GROUP,
        year=year,
        month=month,
        meeting_type=stored_type,
    )
