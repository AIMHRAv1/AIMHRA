from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from accounts import views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="auth-login"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("profile/", views.ProfileView.as_view(), name="auth-profile"),
    path("change-password/", views.ChangePasswordView.as_view(), name="auth-change-password"),
    path("password-reset/", views.PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("users/", views.UserManagementView.as_view(), name="admin-users"),
    path("users/<int:pk>/", views.UserManagementDetailView.as_view(), name="admin-user-detail"),
]
