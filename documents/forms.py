from django import forms
from .models import Document


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title", "category", "description", "file"]
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
            "file": forms.ClearableFileInput(attrs={
                "class": "form-control",
            }),
        }
