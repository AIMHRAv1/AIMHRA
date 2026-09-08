from django.urls import path

from chat import views

urlpatterns = [
    path("sessions/", views.SessionListCreateView.as_view(), name="chat-sessions"),
    path("sessions/<int:session_id>/", views.SessionDetailView.as_view(), name="chat-session-detail"),
    path("sessions/<int:session_id>/send/", views.SendMessageView.as_view(), name="chat-send"),
]
