from django.urls import path

from . import views

app_name = "calendarapp"

urlpatterns = [
    path("", views.calendar_list, name="list"),
    path("book-meeting/", views.book_meeting, name="book_meeting"),
    path("create/", views.calendar_create, name="create"),
    path("<int:pk>/move/", views.calendar_move_event, name="move"),
    path("<int:pk>/", views.calendar_detail, name="detail"),
    path("<int:pk>/edit/", views.calendar_edit, name="edit"),
    path("<int:pk>/delete/", views.calendar_delete, name="delete"),
]
