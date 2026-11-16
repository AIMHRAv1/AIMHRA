from django.core.files.storage import default_storage


def user_photo_url(photo, request=None):
    if not photo:
        return None
    url = default_storage.url(str(photo))
    if request:
        return request.build_absolute_uri(f"/{url.lstrip('/')}")
    return url
