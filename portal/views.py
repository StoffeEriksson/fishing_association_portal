import os
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import render, get_object_or_404
from fishingrights.models import Property, FishingRightShare
from documents.models import Document
from django.contrib import messages
from django.shortcuts import redirect
from documents.forms import DocumentForm


@login_required
def document_list(request):
    org = request.org

    qs = Document.objects.filter(org=org)

    category = request.GET.get("category")
    if category:
        qs = qs.filter(category=category)

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(title__icontains=q)

    qs = qs.order_by("-uploaded_at")

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
def dashboard(request):
    return render(request, "portal/dashboard.html")


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

    paginator = Paginator(qs, 25)  # 25 per sida
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
        .order_by("-share")  # största andel först
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
def document_upload(request):
    org = request.org

    if request.method == "POST":
        form = DocumentForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save(commit=False)
            document.org = org
            document.uploaded_by = request.user
            document.save()

            messages.success(request, "Dokumentet har laddats upp.")
            return redirect("portal:document_list")
    else:
        form = DocumentForm()

    return render(
        request,
        "portal/document_upload.html",
        {
            "form": form,
        },
    )


@login_required
def document_detail(request, pk):
    org = request.org

    doc = get_object_or_404(
        Document.objects.filter(org=org),
        pk=pk
    )

    return render(
        request,
        "portal/document_detail.html",
        {"doc": doc}
    )


@login_required
def document_detail(request, pk):
    org = request.org

    doc = get_object_or_404(
        Document.objects.filter(org=org),
        pk=pk
    )

    ext = os.path.splitext(doc.file.name)[1].lower()

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
            "preview_type": preview_type,
        },
    )
