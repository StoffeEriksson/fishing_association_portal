"""
Backfill workspace folder placement for work documents without a folder.

Only updates documents with folder=NULL (never manually placed).
"""

from django.core.management.base import BaseCommand, CommandError

from core.models import Organization
from documents.models import Document, DocumentFolder, DocumentWorkflowStatus
from documents.services.workspace_folders import (
    ensure_workspace_folder_for_document,
    ensure_workspace_root,
    planned_workspace_target_path_label,
    resolve_workspace_target_key_and_name,
    workspace_target_path_label,
)


class Command(BaseCommand):
    help = (
        "Place work documents (no folder) into workspace category folders under "
        "Arbetsdokument. Use --dry-run to preview without saving."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--org-id",
            type=int,
            default=None,
            help="Organization primary key (tenant scope). Optional if exactly one active org exists.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without saving changes.",
        )

    def handle(self, *args, **options):
        org = self._resolve_org(options["org_id"])
        dry_run = options["dry_run"]

        workspace_root = ensure_workspace_root(org)

        qs = (
            Document.objects.filter(
                org=org,
                is_deleted=False,
                folder__isnull=True,
            )
            .exclude(
                is_archived=True,
                workflow_status=DocumentWorkflowStatus.FINALIZED,
            )
            .select_related("meeting")
            .order_by("pk")
        )

        candidates = list(qs)
        count = len(candidates)
        self.stdout.write(
            self.style.NOTICE(
                f"Found {count} work document(s) without folder for org id={org.pk} "
                f"(dry_run={dry_run})."
            )
        )

        if count == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to backfill."))
            return

        self.stdout.write(
            "id\ttitle\tcategory\tmeeting_id\tcurrent_folder\ttarget_folder\ttarget_path"
        )

        for document in candidates:
            system_key, folder_name = resolve_workspace_target_key_and_name(document)
            current_folder_label = "(none)"

            if dry_run:
                existing = DocumentFolder.objects.filter(
                    org=org,
                    system_key=system_key,
                    is_system_folder=True,
                ).first()
                if existing:
                    target_folder_label = f"id={existing.pk} {existing.name!r}"
                    path_label = workspace_target_path_label(workspace_root, existing)
                else:
                    target_folder_label = f"(new) {folder_name!r}"
                    path_label = planned_workspace_target_path_label(
                        workspace_root, system_key, folder_name
                    )
            else:
                folder = ensure_workspace_folder_for_document(
                    document,
                    workspace_root=workspace_root,
                )
                document.folder = folder
                document.folder_auto_assigned = True
                document.save(
                    update_fields=["folder", "folder_auto_assigned", "updated_at"]
                )
                target_folder_label = f"id={folder.pk} {folder.name!r}"
                path_label = workspace_target_path_label(workspace_root, folder)

            line = (
                f"{document.pk}\t"
                f"{document.title!r}\t"
                f"{document.category}\t"
                f"{document.meeting_id or ''}\t"
                f"{current_folder_label}\t"
                f"{target_folder_label}\t"
                f"{path_label}"
            )

            if dry_run:
                self.stdout.write(f"[dry-run] {line}")
            else:
                self.stdout.write(self.style.SUCCESS(f"[updated] {line}"))

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run complete — no rows were saved."))
        else:
            self.stdout.write(self.style.SUCCESS("Workspace backfill complete."))

    def _resolve_org(self, org_id):
        if org_id is not None:
            org = Organization.objects.filter(pk=org_id, is_active=True).first()
            if org is None:
                raise CommandError(f"No active organization found with id={org_id}.")
            return org

        active = Organization.objects.filter(is_active=True)
        count = active.count()
        if count == 0:
            raise CommandError("No active organization found. Pass --org-id.")
        if count > 1:
            raise CommandError(
                "Multiple active organizations. Pass --org-id explicitly."
            )
        return active.first()
