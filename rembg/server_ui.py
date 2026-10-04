"""Reject remote and foreign file inputs before Gradio moves them to its cache."""

from pathlib import Path

import gradio as gr
from gradio import utils
from gradio_client import utils as client_utils

from .server_security import MAX_IMAGE_BYTES


class UploadOnlyInterface(gr.Interface):
    """All FileData must come from this interface's bounded upload endpoint.

    Component validators run after Gradio's cache mover, which can download
    remote URLs or copy local paths. Validate the raw inputs first, including
    file objects injected into non-file components or nested values.
    """

    async def preprocess_data(self, block_fn, inputs, state, explicit_call=False):
        def require_upload(value):
            raw = value.get("path")
            try:
                if not isinstance(raw, str) or not Path(raw).is_absolute():
                    raise ValueError()
                path = Path(raw)
                resolved = path.resolve(strict=True)
                root = Path(utils.get_upload_folder()).resolve(strict=True)
                if (
                    path.is_symlink()
                    or not resolved.is_relative_to(root)
                    or not resolved.is_file()
                    or raw not in self.upload_file_set
                    or resolved.stat().st_size > MAX_IMAGE_BYTES
                ):
                    raise ValueError()
            except (OSError, ValueError, RuntimeError):
                raise gr.Error("Use a file uploaded through this image form.") from None
            return value

        client_utils.traverse(
            inputs, require_upload, client_utils.is_file_obj_with_meta
        )
        return await super().preprocess_data(block_fn, inputs, state, explicit_call)
