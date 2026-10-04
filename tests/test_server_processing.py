"""Real Pillow/FastAPI/Gradio; synthetic images and a mocked model boundary.

No weights, image fixtures from users, camera or outgoing HTTP are used.
"""

import importlib
import json
import os
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from gradio.route_utils import delete_files_created_by_app
from PIL import Image

from rembg.server_processing import ImageProcessor, validate_image

server = importlib.import_module("rembg.commands.s_command")


def image_bytes(size=(2, 3)):
    buffer = BytesIO()
    Image.new("RGB", size).save(buffer, format="PNG")
    return buffer.getvalue()


class CpuRuntimeTest(unittest.TestCase):
    def test_real_onnx_cpu_and_rembg_pipeline_without_downloaded_weights(self):
        import numpy as np
        import onnxruntime as ort
        from onnxruntime.datasets import get_example

        from rembg.sessions.base import BaseSession

        class SyntheticSession(BaseSession):
            @classmethod
            def download_models(cls, *args, **kwargs):
                return get_example("sigmoid.onnx")

            def predict(self, image, *args, **kwargs):
                pixels = (
                    np.asarray(image.convert("L").resize((5, 4)), dtype=np.float32)
                    / 255
                )
                feeds = {
                    self.inner_session.get_inputs()[0].name: np.stack([pixels] * 3)
                }
                predicted = self.inner_session.run(None, feeds)[0][0]
                mask = Image.fromarray((predicted * 255).astype("uint8")).resize(
                    image.size
                )
                return [mask]

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        session = SyntheticSession(
            "synthetic", options, providers=["CPUExecutionProvider"]
        )
        # Only construction is substituted: the ORT engine, predict, remove,
        # input/output processing and HTTP endpoint execute real library code.
        with patch.object(server, "new_session", return_value=session):
            with TestClient(server.create_server_app()) as client:
                response = client.post(
                    "/api/remove",
                    files={"file": ("test.png", image_bytes(), "image/png")},
                )
                self.assertEqual(response.status_code, 200, response.text)
                with Image.open(BytesIO(response.content)) as output:
                    self.assertEqual(output.mode, "RGBA")
                    self.assertEqual(output.size, (2, 3))
                    self.assertEqual(output.getpixel((0, 0))[3], 127)


class ProcessingBoundaryTest(unittest.TestCase):
    def test_bad_images_are_rejected_before_any_model_is_constructed(self):
        factory = Mock()
        remover = Mock()
        processor = ImageProcessor(factory, remover, ["u2net"])
        for payload in [b"not an image", b"", image_bytes()[:-12]]:
            with self.subTest(payload_size=len(payload)), self.assertRaises(
                HTTPException
            ) as context:
                processor.process(payload, "u2net")
            self.assertEqual(context.exception.status_code, 400)
        with patch("rembg.server_processing.MAX_IMAGE_PIXELS", 5):
            with self.assertRaises(HTTPException) as context:
                processor.process(image_bytes(), "u2net")
        self.assertEqual(context.exception.status_code, 413)
        factory.assert_not_called()
        remover.assert_not_called()

    def test_single_frame_and_output_limits_and_failure_release(self):
        buffer = BytesIO()
        Image.new("RGB", (2, 3)).save(
            buffer,
            format="GIF",
            save_all=True,
            append_images=[Image.new("RGB", (2, 3), "red")],
        )
        with self.assertRaises(HTTPException) as context:
            validate_image(buffer.getvalue())
        self.assertEqual(context.exception.status_code, 400)
        factory = Mock(return_value=object())
        remover = Mock(
            side_effect=[
                RuntimeError("synthetic model failure"),
                b"oversize",
                image_bytes(),
            ]
        )
        processor = ImageProcessor(factory, remover, ["u2net"])
        with self.assertRaises(HTTPException) as context:
            processor.process(image_bytes(), "u2net")
        self.assertEqual(context.exception.status_code, 503)
        self.assertNotIn("synthetic model failure", context.exception.detail)
        with patch("rembg.server_processing.MAX_OUTPUT_BYTES", 2):
            with self.assertRaises(HTTPException) as context:
                processor.process(image_bytes(), "u2net")
        self.assertEqual(context.exception.status_code, 500)
        self.assertEqual(processor.process(image_bytes(), "u2net"), image_bytes())

    def test_sessions_are_reused_and_replaced_including_sam_quantization(self):
        factory = Mock(side_effect=lambda *args, **kwargs: object())
        processor = ImageProcessor(
            factory, Mock(return_value=image_bytes()), ["u2net", "sam"]
        )
        for model, extras in [
            ("u2net", None),
            ("u2net", None),
            ("sam", None),
            ("sam", '{"sam_quant":true}'),
        ]:
            processor.process(image_bytes(), model, extras=extras)
        self.assertEqual(factory.call_count, 3)
        self.assertEqual(factory.call_args.kwargs, {"sam_quant": True})
        with self.assertRaises(HTTPException) as context:
            processor.process(image_bytes(), "u2net_custom")
        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(factory.call_count, 3)


class MountedServerTest(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)
        env = patch.dict(os.environ, {"GRADIO_TEMP_DIR": self.cache.name})
        env.start()
        self.addCleanup(env.stop)

    def test_raw_ui_inputs_cannot_download_urls_or_copy_foreign_files(self):
        png = image_bytes()
        factory = Mock(return_value=object())
        with patch.object(server, "new_session", factory), patch.object(
            server, "remove", return_value=png
        ), tempfile.TemporaryDirectory() as directory:
            foreign = Path(directory) / "foreign.png"
            foreign.write_bytes(png)
            app = server.create_server_app()
            interface = app.app.state.rembg_interface
            with TestClient(app) as client:
                upload = client.post(
                    "/gradio_api/upload",
                    files={"files": ("test.png", png, "image/png")},
                )
                self.assertEqual(upload.status_code, 200)
                uploaded = upload.json()[0]
                meta = {"_type": "gradio.FileData"}
                link = Path(self.cache.name) / "foreign-link.png"
                link.symlink_to(foreign)
                interface.upload_file_set.add(str(link))
                unregistered = Path(self.cache.name) / "not-uploaded.png"
                unregistered.write_bytes(png)
                cases = [
                    (0, "https://synthetic.invalid/image.png"),
                    (0, str(foreign)),
                    (0, str(link)),
                    (0, str(unregistered)),
                    # Cache movement precedes validation for every component,
                    # including a FileData injected into the Arguments textbox.
                    (8, "https://synthetic.invalid/nested.png"),
                ]
                for index, path in cases:
                    with self.subTest(index=index, path_kind=Path(path).name):
                        data = [
                            {"path": uploaded, "meta": meta},
                            "u2net",
                            False,
                            240,
                            10,
                            10,
                            False,
                            False,
                            "",
                        ]
                        data[index] = {"path": path, "meta": meta}
                        with patch(
                            "gradio.processing_utils.async_ssrf_protected_download",
                            new_callable=AsyncMock,
                        ) as download, patch.object(
                            interface.input_components[0],
                            "async_move_resource_to_block_cache",
                            new_callable=AsyncMock,
                        ) as copy:
                            prediction = client.post(
                                "/gradio_api/call/remove_background",
                                json={"data": data},
                            )
                            self.assertEqual(prediction.status_code, 200)
                            result = client.get(
                                "/gradio_api/call/remove_background/"
                                + prediction.json()["event_id"]
                            )
                            self.assertIn("event: error", result.text, result.text)
                            download.assert_not_called()
                            copy.assert_not_called()
                            factory.assert_not_called()
                self.assertEqual(foreign.read_bytes(), png)

    def test_mounted_ui_upload_and_api_share_validation_and_cached_session(self):
        png = image_bytes()
        factory = Mock(return_value=object())
        with patch.object(server, "new_session", factory), patch.object(
            server, "remove", return_value=png
        ):
            app = server.create_server_app()
            interface = app.app.state.rembg_interface
            with TestClient(app) as client, tempfile.TemporaryDirectory() as directory:
                response = client.post(
                    "/api/remove", files={"file": ("test.png", png, "image/png")}
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.content, png)
                input_path = Path(directory) / "input.png"
                input_path.write_bytes(png)
                output = interface.fn(
                    str(input_path), "u2net", False, 240, 10, 10, False, False, ""
                )
                self.assertEqual(output.size, (2, 3))
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(client.get("/").status_code, 200)
                upload = client.post(
                    "/gradio_api/upload",
                    files={"files": ("test.png", png, "image/png")},
                )
                self.assertEqual(upload.status_code, 200, upload.text)
                self.assertTrue(upload.json())
                # Exercise Gradio's actual preprocessing, queue and image cache.
                prediction = client.post(
                    "/gradio_api/call/remove_background",
                    json={
                        "data": [
                            {
                                "path": upload.json()[0],
                                "meta": {"_type": "gradio.FileData"},
                            },
                            "u2net",
                            False,
                            240,
                            10,
                            10,
                            False,
                            False,
                            "",
                        ]
                    },
                )
                self.assertEqual(prediction.status_code, 200, prediction.text)
                result = client.get(
                    "/gradio_api/call/remove_background/"
                    + prediction.json()["event_id"]
                )
                self.assertIn("event: complete", result.text, result.text)
                output_data = json.loads(
                    result.text.split("event: complete\ndata: ", 1)[1].splitlines()[0]
                )
                cached_path = Path(output_data[0]["path"])
                self.assertTrue(cached_path.is_file())
                self.assertTrue(cached_path.is_relative_to(self.cache.name))
                self.assertEqual(factory.call_count, 1)
                delete_files_created_by_app(interface, age=None)
                self.assertFalse(cached_path.exists())
                response = client.post(
                    "/api/remove",
                    files={"file": ("bad.png", b"not an image", "image/png")},
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(interface.delete_cache, (60, 3600))
                self.assertEqual(interface._queue.max_size, 4)
                self.assertEqual(interface.max_file_size, 10 * 1024 * 1024)

    def test_api_busy_while_ui_inference_runs_and_recovers_after_completion(self):
        started, release = threading.Event(), threading.Event()
        errors = []
        png = image_bytes()

        def remove(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise TimeoutError("synthetic blocked model")
            return png

        with patch.object(server, "new_session", return_value=object()), patch.object(
            server, "remove", side_effect=remove
        ):
            app = server.create_server_app()
            with TestClient(app) as client, tempfile.TemporaryDirectory() as directory:
                input_path = Path(directory) / "input.png"
                input_path.write_bytes(png)

                def run_ui():
                    try:
                        app.app.state.rembg_interface.fn(
                            str(input_path),
                            "u2net",
                            False,
                            240,
                            10,
                            10,
                            False,
                            False,
                            "",
                        )
                    except Exception as exc:
                        errors.append(exc)

                worker = threading.Thread(target=run_ui)
                worker.start()
                try:
                    self.assertTrue(started.wait(3))
                    response = client.post(
                        "/api/remove", files={"file": ("test.png", png, "image/png")}
                    )
                    self.assertEqual(response.status_code, 503, response.text)
                    self.assertEqual(response.headers["retry-after"], "1")
                finally:
                    release.set()
                    worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                response = client.post(
                    "/api/remove", files={"file": ("test.png", png, "image/png")}
                )
                self.assertEqual(response.status_code, 200)

    def test_color_and_erosion_invalid_input_never_become_server_errors(self):
        png = image_bytes()
        factory = Mock(return_value=object())
        with patch.object(server, "new_session", factory), patch.object(
            server, "remove", return_value=png
        ):
            with TestClient(server.create_server_app()) as client:
                for color in ["", "red", "1,2,3", "1,2,3,256", "1,2,3,-1"]:
                    response = client.post(
                        "/api/remove",
                        params={"bgc": color},
                        files={"file": ("test.png", png, "image/png")},
                    )
                    self.assertEqual(response.status_code, 400, response.text)
                response = client.post(
                    "/api/remove",
                    data={"ae": 1000000},
                    files={"file": ("test.png", png, "image/png")},
                )
                self.assertEqual(response.status_code, 422, response.text)
                factory.assert_not_called()
                response = client.post(
                    "/api/remove",
                    params={"bgc": "1,2,3,255"},
                    files={"file": ("test.png", png, "image/png")},
                )
                self.assertEqual(response.status_code, 200, response.text)
