import os

def guess_extension(filename: str | None, content_type: str | None) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext:
        return ext
    if content_type:
        if "pdf" in content_type:
            return ".pdf"
        if "png" in content_type:
            return ".png"
        if "jpeg" in content_type or "jpg" in content_type:
            return ".jpg"
    return ".bin"
