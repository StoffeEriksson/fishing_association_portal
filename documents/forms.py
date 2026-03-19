from django import forms
from .models import Document, DocumentVersion


class DocumentCreateForm(forms.ModelForm):
    file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"class": "form-control"})
    )

    class Meta:
        model = Document
        fields = ["title", "category", "description"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ange dokumenttitel",
            }),
            "category": forms.Select(attrs={
                "class": "form-select",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Kort beskrivning av dokumentet",
            }),
        }


class DocumentVersionForm(forms.ModelForm):
    class Meta:
        model = DocumentVersion
        fields = ["file", "notes"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={
                "class": "form-control",
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Beskriv vad som ändrats i denna version",
            }),
        }


class DocumentUpdateForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title", "category", "description"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ange dokumenttitel",
            }),
            "category": forms.Select(attrs={
                "class": "form-select",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Kort beskrivning av dokumentet",
            }),
        }
