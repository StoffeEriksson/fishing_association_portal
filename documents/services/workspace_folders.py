"""
Idempotent workspace folder tree for work documents (not archive).

Creates system folders under workspace-root. Does not modify documents unless
called from the backfill command.
"""

from documents.models import Document, DocumentCategory, DocumentFolder, DocumentFolderType

WORKSPACE_ROOT_SYSTEM_KEY = "workspace"

WORKSPACE_MEETING_DOCUMENTS_KEY = "workspace/meeting-documents"
WORKSPACE_MEETING_DOCUMENTS_NAME = "Pågående mötesdokument"

WORKSPACE_CATEGORY_TARGETS = {
    DocumentCategory.PROTOCOL: ("workspace/protocol-drafts", "Protokollutkast"),
    DocumentCategory.BYLAWS: ("workspace/bylaws", "Stadgar"),
    DocumentCategory.NOTICE: ("workspace/notices", "Kallelser"),
    DocumentCategory.MOTION: ("workspace/motions", "Motioner"),
    DocumentCategory.DECISION: ("workspace/decisions", "Beslut"),
    DocumentCategory.OTHER: ("workspace/other", "Övrigt"),
}

WORKSPACE_OTHER_KEY = "workspace/other"
WORKSPACE_OTHER_NAME = "Övrigt"


def is_archive_system_key(system_key: str) -> bool:
    key = (system_key or "").strip().lower()
    return key == "archive" or key.startswith("archive/")


def build_folder_in_archive_map(org) -> dict[int, bool]:
    folders = list(DocumentFolder.objects.filter(org=org).only("pk", "parent_id", "system_key"))
    by_id = {f.pk: f for f in folders}
    archive_memo: dict[int, bool] = {}

    def is_archive_folder(folder):
        if folder is None:
            return False
        cached = archive_memo.get(folder.pk)
        if cached is not None:
            return cached
        if is_archive_system_key(folder.system_key):
            archive_memo[folder.pk] = True
            return True
        if folder.parent_id is None:
            archive_memo[folder.pk] = False
            return False
        parent = by_id.get(folder.parent_id)
        in_archive = is_archive_folder(parent)
        archive_memo[folder.pk] = in_archive
        return in_archive

    return {f.pk: is_archive_folder(f) for f in folders}


def ensure_workspace_root(org) -> DocumentFolder:
    folder, _created = DocumentFolder.objects.get_or_create(
        org=org,
        system_key=WORKSPACE_ROOT_SYSTEM_KEY,
        is_system_folder=True,
        defaults={
            "name": "Arbetsdokument",
            "parent": None,
            "folder_type": DocumentFolderType.STATIC,
        },
    )
    return folder


def resolve_workspace_target_key_and_name(document: Document) -> tuple[str, str]:
    """
    Return (system_key, folder display name) for a work document.

    Meeting-linked docs go to Pågående mötesdokument.
    protocol without meeting → Protokollutkast (never official protocol archive).
    """
    if document.meeting_id is not None:
        return WORKSPACE_MEETING_DOCUMENTS_KEY, WORKSPACE_MEETING_DOCUMENTS_NAME

    category = (document.category or "").strip()
    if category in WORKSPACE_CATEGORY_TARGETS:
        return WORKSPACE_CATEGORY_TARGETS[category]

    return WORKSPACE_OTHER_KEY, WORKSPACE_OTHER_NAME


def _get_or_create_workspace_system_folder(
    *,
    org,
    parent: DocumentFolder,
    name: str,
    system_key: str,
) -> DocumentFolder:
    folder, _created = DocumentFolder.objects.get_or_create(
        org=org,
        system_key=system_key,
        is_system_folder=True,
        defaults={
            "name": name,
            "parent": parent,
            "folder_type": DocumentFolderType.STATIC,
            "is_system_folder": True,
        },
    )
    return folder


def ensure_workspace_folder_for_document(
    document: Document,
    *,
    workspace_root: DocumentFolder | None = None,
) -> DocumentFolder:
    """Return target workspace folder for *document*; create missing system folders."""
    if document.org_id is None:
        raise ValueError("Document must belong to an organization.")

    org = document.org
    root = workspace_root or ensure_workspace_root(org)
    system_key, name = resolve_workspace_target_key_and_name(document)
    return _get_or_create_workspace_system_folder(
        org=org,
        parent=root,
        name=name,
        system_key=system_key,
    )


def workspace_target_path_label(workspace_root: DocumentFolder, folder: DocumentFolder) -> str:
    return f"{workspace_root.name} / {folder.name}"


def planned_workspace_target_path_label(
    workspace_root: DocumentFolder,
    system_key: str,
    folder_name: str,
) -> str:
    return f"{workspace_root.name} / {folder_name} [{system_key}]"
