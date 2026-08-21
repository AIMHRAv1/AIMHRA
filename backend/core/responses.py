"""Helpers for consistent success envelopes."""


def ok(data=None, status=200, headers=None):
    payload = {"success": True}
    if data is not None:
        payload["data"] = data
    from rest_framework.response import Response

    return Response(payload, status=status, headers=headers)
