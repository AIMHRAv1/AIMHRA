from rest_framework import generics

from audit.models import AuditLog
from audit.serializers import AuditLogSerializer
from core.permissions import IsAdmin


class AuditLogListView(generics.ListAPIView):
    """Admin-only audit trail with optional action/user filters."""

    serializer_class = AuditLogSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        qs = AuditLog.objects.select_related("user").all()
        action = self.request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)
        username = self.request.query_params.get("username")
        if username:
            qs = qs.filter(user__username__icontains=username)
        return qs
