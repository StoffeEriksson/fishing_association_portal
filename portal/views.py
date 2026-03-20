import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.http import HttpResponse
from django.template.loader import render_to_string

from fishingrights.models import FishingRightShare, Property
from documents.forms import DocumentCreateForm, DocumentUpdateForm, DocumentVersionForm, TemplateDocumentCreateForm
from documents.models import (
    Document,
    DocumentActivity,
    DocumentSourceType,
    DocumentTemplate,
    DocumentVersion,
    
)
from documents.utils import log_document_activity




def render_template_content(template_content, cleaned_data):
    attendees_raw = cleaned_data.get("attendees", "").strip()

    if attendees_raw:
        attendees_list = [
            line.strip() for line in attendees_raw.splitlines() if line.strip()
        ]
        attendees_html = "<ul>" + "".join(f"<li>{name}</li>" for name in attendees_list) + "</ul>"
    else:
        attendees_html = "<ul><li></li></ul>"

    replacements = {
        "{{ date }}": cleaned_data.get("date").strftime("%Y-%m-%d") if cleaned_data.get("date") else "",
        "{{ time }}": cleaned_data.get("time").strftime("%H:%M") if cleaned_data.get("time") else "",
        "{{ location }}": cleaned_data.get("location", ""),
        "{{ attendees_html }}": attendees_html,
    }

    content = template_content
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)

    return content


@login_required
def dashboard(request):
    org = request.org

    recent_documents = Document.objects.filter(
        org=org,
        is_deleted=False,
    ).order_by("-updated_at")[:5]

    recent_activities = DocumentActivity.objects.filter(
        document__org=org
    ).select_related("document", "user").order_by("-created_at")[:5]

    return render(
        request,
        "portal/dashboard.html",
        {
            "recent_documents": recent_documents,
            "recent_activities": recent_activities,
        },
    )


@login_required
def property_list(request):
    org = request.org

    qs = Property.objects.filter(org=org).order_by("designation")

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(designation__icontains=q) |
            Q(external_id__icontains=q)
        )

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "portal/property_list.html",
        {"page_obj": page_obj, "q": q},
    )


@login_required
def property_detail(request, pk):
    org = request.org

    property_obj = get_object_or_404(
        Property.objects.filter(org=org),
        pk=pk
    )

    shares = (
        FishingRightShare.objects
        .filter(property=property_obj)
        .select_related("holder")
        .order_by("-share")
    )

    total_share = shares.aggregate(total=Sum("share"))["total"] or 0

    return render(
        request,
        "portal/property_detail.html",
        {
            "property": property_obj,
            "shares": shares,
            "total_share": total_share,
        },
    )


@login_required
def document_list(request):
    org = request.org

    qs = Document.objects.filter(org=org, is_deleted=False)

    category = request.GET.get("category")
    if category:
        qs = qs.filter(category=category)

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(title__icontains=q)

    qs = qs.order_by("-updated_at")

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "portal/document_list.html",
        {
            "page_obj": page_obj,
            "q": q,
            "category": category,
        },
    )


@login_required
def document_upload(request):
    org = request.org

    if request.method == "POST":
        form = DocumentCreateForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]

            document = form.save(commit=False)
            document.org = org
            document.uploaded_by = request.user
            document.source_type = DocumentSourceType.UPLOADED
            document.save()

            DocumentVersion.objects.create(
                document=document,
                version_number=1,
                file=uploaded_file,
                uploaded_by=request.user,
            )

            log_document_activity(
                document=document,
                user=request.user,
                action="created",
                message="Dokument skapades",
            )

            messages.success(request, "Dokumentet har laddats upp.")
            return redirect("portal:document_list")
    else:
        form = DocumentCreateForm()

    return render(
        request,
        "portal/document_upload.html",
        {"form": form},
    )


@login_required
def document_upload_version(request, pk):
    org = request.org

    document = get_object_or_404(
        Document.objects.filter(org=org, is_deleted=False),
        pk=pk,
    )

    current_version = document.current_version
    next_version_number = 1 if current_version is None else current_version.version_number + 1

    if request.method == "POST":
        form = DocumentVersionForm(request.POST, request.FILES)
        if form.is_valid():
            version = form.save(commit=False)
            version.document = document
            version.version_number = next_version_number
            version.uploaded_by = request.user
            version.save()

            log_document_activity(
                document=document,
                user=request.user,
                action="version_created",
                message=f"Ny version (v{next_version_number}) laddades upp",
            )

            messages.success(request, f"Ny version (v{next_version_number}) har laddats upp.")
            return redirect("portal:document_detail", pk=document.pk)
    else:
        form = DocumentVersionForm()

    return render(
        request,
        "portal/document_upload_version.html",
        {
            "document": document,
            "form": form,
            "next_version_number": next_version_number,
        },
    )


@login_required
def document_detail(request, pk):
    org = request.org

    doc = get_object_or_404(
        Document.objects.filter(org=org, is_deleted=False).prefetch_related("versions"),
        pk=pk,
    )

    activities = doc.activities.select_related("user").order_by("-created_at")
    current_version = doc.current_version

    if not current_version:
        preview_type = "other"
    else:
        ext = os.path.splitext(current_version.file.name)[1].lower()

        if ext == ".pdf":
            preview_type = "pdf"
        elif ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
            preview_type = "image"
        else:
            preview_type = "other"

    return render(
        request,
        "portal/document_detail.html",
        {
            "doc": doc,
            "current_version": current_version,
            "preview_type": preview_type,
            "versions": doc.versions.all(),
            "activities": activities,
        },
    )


@login_required
def document_edit(request, pk):
    org = request.org

    document = get_object_or_404(
        Document.objects.filter(org=org, is_deleted=False),
        pk=pk,
    )

    if request.method == "POST":
        form = DocumentUpdateForm(request.POST, instance=document)
        if form.is_valid():
            form.save()

            log_document_activity(
                document=document,
                user=request.user,
                action="updated",
                message="Dokument uppdaterades",
            )

            messages.success(request, "Dokumentet har uppdaterats.")
            return redirect("portal:document_detail", pk=document.pk)
    else:
        form = DocumentUpdateForm(instance=document)

    return render(
        request,
        "portal/document_edit.html",
        {
            "document": document,
            "form": form,
        },
    )


@login_required
def document_delete(request, pk):
    org = request.org

    document = get_object_or_404(
        Document.objects.filter(org=org, is_deleted=False),
        pk=pk,
    )

    if request.method == "POST":
        document.is_deleted = True
        document.deleted_at = timezone.now()
        document.deleted_by = request.user
        document.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "updated_at"])

        log_document_activity(
            document=document,
            user=request.user,
            action="deleted",
            message=f"Dokumentet '{document.title}' markerades som borttaget",
        )

        messages.success(request, f"Dokumentet '{document.title}' har tagits bort.")
        return redirect("portal:document_list")

    return render(
        request,
        "portal/document_confirm_delete.html",
        {
            "document": document,
        },
    )


@login_required
def document_trash(request):
    org = request.org

    qs = Document.objects.filter(org=org, is_deleted=True).order_by("-deleted_at")

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(title__icontains=q)

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "portal/document_trash.html",
        {
            "page_obj": page_obj,
            "q": q,
        },
    )


@login_required
def document_restore(request, pk):
    org = request.org

    document = get_object_or_404(
        Document.objects.filter(org=org, is_deleted=True),
        pk=pk,
    )

    if request.method == "POST":
        document.is_deleted = False
        document.deleted_at = None
        document.deleted_by = None
        document.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "updated_at"])

        log_document_activity(
            document=document,
            user=request.user,
            action="restored",
            message=f"Dokumentet '{document.title}' återställdes",
        )

        messages.success(request, f"Dokumentet '{document.title}' har återställts.")
        return redirect("portal:document_trash")

    return render(
        request,
        "portal/document_confirm_restore.html",
        {
            "document": document,
        },
    )


DOCUMENT_CATEGORIES = [
    {"key": "protocol", "label": "Protokoll", "icon": "bi-folder"},
    {"key": "bylaws", "label": "Stadgar", "icon": "bi-folder"},
    {"key": "notice", "label": "Kallelser", "icon": "bi-folder"},
    {"key": "motion", "label": "Motioner", "icon": "bi-folder"},
    {"key": "decision", "label": "Beslut", "icon": "bi-folder"},
    {"key": "other", "label": "Övrigt", "icon": "bi-folder"},
]


@login_required
def document_folder_list(request):
    org = request.org

    folder_data = []
    for category in DOCUMENT_CATEGORIES:
        count = Document.objects.filter(
            org=org,
            category=category["key"],
            is_deleted=False,
        ).count()

        folder_data.append({
            "key": category["key"],
            "label": category["label"],
            "icon": category["icon"],
            "count": count,
        })

    return render(
        request,
        "portal/documents/folder_list.html",
        {"folders": folder_data},
    )


@login_required
def template_list(request):
    templates = DocumentTemplate.objects.all()

    return render(
        request,
        "portal/documents/template_list.html",
        {"templates": templates},
    )


@login_required
def create_from_template(request, template_id):
    template = get_object_or_404(DocumentTemplate, id=template_id)

    if request.method == "POST":
        form = TemplateDocumentCreateForm(request.POST)
        if form.is_valid():
            content = render_template_content(template.content, form.cleaned_data)

            document = Document.objects.create(
                org=request.org,
                title=form.cleaned_data["title"],
                category=template.category,
                description="Skapat från mall",
                content=content,
                template=template,
                source_type=DocumentSourceType.TEMPLATE,
                uploaded_by=request.user,
            )

            log_document_activity(
                document=document,
                user=request.user,
                action="created",
                message=f"Dokument skapades från mallen '{template.name}'",
            )

            messages.success(request, f"Dokumentet '{document.title}' skapades från mall.")
            return redirect("portal:document_detail", pk=document.pk)
    else:
        form = TemplateDocumentCreateForm(
            initial={
                "title": template.name,
            }
        )

    return render(
        request,
        "portal/documents/create_from_template.html",
        {
            "template": template,
            "form": form,
        },
    )


@login_required
def document_print_view(request, pk):
    doc = get_object_or_404(
        Document.objects.filter(org=request.org, is_deleted=False),
        pk=pk,
    )

    return render(
        request,
        "portal/documents/document_print.html",
        {"doc": doc, "org": request.org},
    )
