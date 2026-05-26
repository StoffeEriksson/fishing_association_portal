"""
Backfill archive folder placement for finalized meeting-linked documents.

Only updates documents that are still auto-placeable (no manual folder lock).
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from core.models import Organization
from documents.models import Document, DocumentWorkflowStatus
from documents.services.archive_folders import ensure_archive_path


class Command(BaseCommand):
    help = (
        "Place finalized, archived meeting documents into the archive folder tree. "
        "Use --dry-run to preview without saving."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--org-id",
            type=int,
            required=True,
            help="Organization primary key (tenant scope).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without saving changes.",
        )

    def handle(self, *args, **options):
        org_id = options["org_id"]
        dry_run = options["dry_run"]

        org = Organization.objects.filter(pk=org_id, is_active=True).first()
        if org is None:
            raise CommandError(f"No active organization found with id={org_id}.")

        qs = (
            Document.objects.filter(
                org=org,
                meeting__isnull=False,
                is_deleted=False,
                is_archived=True,
                workflow_status=DocumentWorkflowStatus.FINALIZED,
            )
            .filter(Q(folder__isnull=True) | Q(folder_auto_assigned=True))
            .select_related("meeting", "folder")
            .order_by("pk")
        )

        count = qs.count()
        self.stdout.write(
            self.style.NOTICE(
                f"Found {count} document(s) for org id={org_id} (dry_run={dry_run})."
            )
        )

        for document in qs:
            folder = ensure_archive_path(document)
            system_key = folder.system_key or "(empty)"

            line = (
                f"id={document.pk}\t"
                f"title={document.title!r}\t"
                f"meeting_id={document.meeting_id}\t"
                f"target_folder_id={folder.pk}\t"
                f"system_key={system_key}"
            )

            if dry_run:
                self.stdout.write(f"[dry-run] {line}")
            else:
                document.folder = folder
                document.folder_auto_assigned = True
                document.save(update_fields=["folder", "folder_auto_assigned", "updated_at"])
                self.stdout.write(self.style.SUCCESS(f"[updated] {line}"))

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run complete — no rows were saved."))
        else:
            self.stdout.write(self.style.SUCCESS("Backfill complete."))
