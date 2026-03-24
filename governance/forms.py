from django import forms
from .models import BoardMembership


class BoardMembershipForm(forms.ModelForm):
    class Meta:
        model = BoardMembership
        fields = [
            "user",
            "role",
            "is_active",
            "can_manage_members",
            "can_manage_matters",
            "can_manage_documents",
        ]
        widgets = {
            "user": forms.Select(attrs={"class": "form-select"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_members": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_matters": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_documents": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
