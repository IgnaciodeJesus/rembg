import logging
import re
import webbrowser
from io import BytesIO
from typing import Optional

import click
import gradio as gr
import uvicorn
from asyncer import asyncify
from fastapi import Depends, FastAPI, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from starlette.responses import Response

from .. import __version__
from ..bg import remove
from ..server_processing import ImageProcessor, background_color
from ..server_security import MAX_IMAGE_BYTES, RequestSizeLimit, fetch_image
from ..session_factory import new_session
from ..sessions import sessions_names


@click.command(  # type: ignore
    name="s",
    help="for a http server",
)
@click.option(
    "-p",
    "--port",
    default=7000,
    type=int,
    show_default=True,
    help="port",
)
@click.option(
    "-h",
    "--host",
    default="127.0.0.1",
    type=str,
    show_default=True,
    help="host",
)
@click.option(
    "-l",
    "--log_level",
    default="info",
    type=str,
    show_default=True,
    help="log level",
)
@click.option(
    "-t",
    "--threads",
    default=None,
    type=click.IntRange(1, 8),
    show_default=True,
    help="number of worker threads (inference remains serialized)",
)
def s_command(port: int, host: str, log_level: str, threads: int) -> None:
    """
    Command-line interface for running the FastAPI web server.

    This function starts the FastAPI web server with the specified port and log level.
    If the number of worker threads is specified, it sets the thread limiter accordingly.
    """
    uvicorn.run(
        create_server_app(port, threads, open_browser=True),
        host=host,
        port=port,
        log_level=log_level,
        limit_concurrency=16,
        access_log=False,
    )


def create_server_app(port=7000, threads=None, open_browser=False):
    """Construct the optional server without opening a socket or loading weights."""
    http_models = [name for name in sessions_names if not name.endswith("_custom")]
    processor = ImageProcessor(new_session, remove, http_models)
    model_pattern = r"^(?:" + "|".join(re.escape(name) for name in http_models) + r")$"
    tags_metadata = [
        {
            "name": "Background Removal",
            "description": "Endpoints that perform background removal with different image sources.",
            "externalDocs": {
                "description": "GitHub Source",
                "url": "https://github.com/danielgatis/rembg",
            },
        },
    ]
    app = FastAPI(
        title="Rembg",
        description="Rembg is a tool to remove images background. That is it.",
        version=__version__,
        contact={
            "name": "Daniel Gatis",
            "url": "https://github.com/danielgatis",
            "email": "danielgatis@gmail.com",
        },
        license_info={
            "name": "MIT License",
            "url": "https://github.com/danielgatis/rembg/blob/main/LICENSE.txt",
        },
        openapi_tags=tags_metadata,
        docs_url="/api",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_credentials=False,
        allow_origins=[],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    class CommonQueryParams:
        def __init__(
            self,
            model: str = Query(
                description="Model to use when processing image",
                regex=model_pattern,
                default="u2net",
            ),
            a: bool = Query(default=False, description="Enable Alpha Matting"),
            af: int = Query(
                default=240,
                ge=0,
                le=255,
                description="Alpha Matting (Foreground Threshold)",
            ),
            ab: int = Query(
                default=10,
                ge=0,
                le=255,
                description="Alpha Matting (Background Threshold)",
            ),
            ae: int = Query(
                default=10,
                ge=0,
                le=255,
                description="Alpha Matting (Erode Structure Size)",
            ),
            om: bool = Query(default=False, description="Only Mask"),
            ppm: bool = Query(default=False, description="Post Process Mask"),
            bgc: Optional[str] = Query(default=None, description="Background Color"),
            extras: Optional[str] = Query(
                default=None, description="Extra parameters as JSON"
            ),
        ):
            self.model = model
            self.a = a
            self.af = af
            self.ab = ab
            self.ae = ae
            self.om = om
            self.ppm = ppm
            self.extras = extras
            self.bgc = background_color(bgc)

    class CommonQueryPostParams:
        def __init__(
            self,
            model: str = Form(
                description="Model to use when processing image",
                regex=model_pattern,
                default="u2net",
            ),
            a: bool = Form(default=False, description="Enable Alpha Matting"),
            af: int = Form(
                default=240,
                ge=0,
                le=255,
                description="Alpha Matting (Foreground Threshold)",
            ),
            ab: int = Form(
                default=10,
                ge=0,
                le=255,
                description="Alpha Matting (Background Threshold)",
            ),
            ae: int = Form(
                default=10,
                ge=0,
                le=255,
                description="Alpha Matting (Erode Structure Size)",
            ),
            om: bool = Form(default=False, description="Only Mask"),
            ppm: bool = Form(default=False, description="Post Process Mask"),
            bgc: Optional[str] = Query(default=None, description="Background Color"),
            extras: Optional[str] = Query(
                default=None, description="Extra parameters as JSON"
            ),
        ):
            self.model = model
            self.a = a
            self.af = af
            self.ab = ab
            self.ae = ae
            self.om = om
            self.ppm = ppm
            self.extras = extras
            self.bgc = background_color(bgc)

    def im_without_bg(content: bytes, commons: CommonQueryParams) -> Response:
        return Response(
            processor.process(
                content,
                commons.model,
                extras=commons.extras,
                alpha_matting=commons.a,
                alpha_matting_foreground_threshold=commons.af,
                alpha_matting_background_threshold=commons.ab,
                alpha_matting_erode_size=commons.ae,
                only_mask=commons.om,
                post_process_mask=commons.ppm,
                bgcolor=commons.bgc,
            ),
            media_type="image/png",
        )

    @app.on_event("startup")
    def startup():
        try:
            if open_browser:
                webbrowser.open(f"http://localhost:{port}")
        except Exception:
            logging.getLogger(__name__).info(
                "Browser launch unavailable; server continues"
            )

        if threads is not None:
            from anyio import CapacityLimiter
            from anyio.lowlevel import RunVar

            RunVar("_default_thread_limiter").set(CapacityLimiter(threads))

    @app.get(
        path="/api/remove",
        tags=["Background Removal"],
        summary="Remove from URL",
        description="Removes the background from an image obtained by retrieving an URL.",
    )
    async def get_index(
        url: str = Query(
            default=..., description="URL of the image that has to be processed."
        ),
        commons: CommonQueryParams = Depends(),
    ):
        file = await fetch_image(url)
        return await asyncify(im_without_bg)(file, commons)

    @app.post(
        path="/api/remove",
        tags=["Background Removal"],
        summary="Remove from Stream",
        description="Removes the background from an image sent within the request itself.",
    )
    async def post_index(
        file: bytes = File(
            default=...,
            description="Image file (byte stream) that has to be processed.",
        ),
        commons: CommonQueryPostParams = Depends(),
    ):
        return await asyncify(im_without_bg)(file, commons)  # type: ignore

    def gr_app(app):
        def inference(input_path, model, *args):
            a, af, ab, ae, om, ppm, cmd_args = args

            kwargs = {
                "alpha_matting": a,
                "alpha_matting_foreground_threshold": af,
                "alpha_matting_background_threshold": ab,
                "alpha_matting_erode_size": ae,
                "only_mask": om,
                "post_process_mask": ppm,
            }

            with open(input_path, "rb") as i:
                input = i.read(MAX_IMAGE_BYTES + 1)
            if len(input) > MAX_IMAGE_BYTES:
                raise ValueError("Image exceeds server size limit")
            output = processor.process(input, model, extras=cmd_args, **kwargs)
            # Gradio owns this image's cache lifecycle; no untracked temp file.
            with Image.open(BytesIO(output)) as result:
                return result.copy()

        from ..server_ui import UploadOnlyInterface

        interface = UploadOnlyInterface(
            inference,
            [
                gr.components.File(
                    type="filepath", file_types=["image"], label="Input"
                ),
                gr.components.Dropdown(http_models, value="u2net", label="Models"),
                gr.components.Checkbox(value=True, label="Alpha matting"),
                gr.components.Slider(
                    value=240, minimum=0, maximum=255, label="Foreground threshold"
                ),
                gr.components.Slider(
                    value=10, minimum=0, maximum=255, label="Background threshold"
                ),
                gr.components.Slider(
                    value=40, minimum=0, maximum=255, label="Erosion size"
                ),
                gr.components.Checkbox(value=False, label="Only mask"),
                gr.components.Checkbox(value=True, label="Post process mask"),
                gr.components.Textbox(label="Arguments"),
            ],
            gr.components.Image(type="pil", label="Output"),
            concurrency_limit=1,
            delete_cache=(60, 3600),
            analytics_enabled=False,
            api_name="remove_background",
            flagging_mode="never",
        )

        interface.queue(max_size=4, api_open=False, default_concurrency_limit=1)
        app.state.rembg_interface = interface
        app.state.rembg_processor = processor
        app = gr.mount_gradio_app(
            app, interface, path="/", max_file_size=MAX_IMAGE_BYTES, show_error=False
        )
        return app

    return RequestSizeLimit(gr_app(app))
