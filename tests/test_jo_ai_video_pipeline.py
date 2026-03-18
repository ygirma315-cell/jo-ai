from __future__ import annotations

import base64
import io
import unittest

import main
from bot.services import jo_video_model as jo_video_module
from bot.services.ai_service import AIServiceError, GeneratedImageResult, GeneratedVideoResult
from bot.services.jo_video_model import JOAIVideoModelEngine, JOAIVideoOptions, JOAIVideoProgress, JOAIVideoResult

_SMALL_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)

try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - runtime optional
    Image = None  # type: ignore[assignment]



def _png_bytes(color: tuple[int, int, int] = (32, 128, 220), size: tuple[int, int] = (768, 1344)) -> bytes:
    if Image is None:
        return base64.b64decode(_SMALL_PNG_BASE64)
    image = Image.new("RGB", size, color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class _FakePollinationsService:
    def __init__(self, *, image_bytes: bytes | None = None, fail_image: bool = False) -> None:
        self.api_key = "test-key"
        self.video_model_grok_text_to_video = "grok-video"
        self._image_bytes = image_bytes or _png_bytes()
        self._fail_image = fail_image

    async def generate_image(self, **_kwargs):
        if self._fail_image:
            raise RuntimeError("image provider failed")
        return GeneratedImageResult(image_bytes=self._image_bytes, image_url=None)

    async def generate_video(self, **_kwargs):
        return GeneratedVideoResult(video_bytes=b"video", video_url=None, mime_type="video/mp4")


class _FakeImageService:
    def __init__(self, image_bytes: bytes | None = None) -> None:
        self._image_bytes = image_bytes or _png_bytes((150, 90, 30))

    async def generate_image(self, *_args, **_kwargs):
        return GeneratedImageResult(image_bytes=self._image_bytes, image_url=None)


class TestMainIntentRouting(unittest.TestCase):
    def test_edit_intent_routes_to_image_edit_even_with_jo_video_selected(self) -> None:
        payload = main.JOChatRequest(message="remove her glasses", selected_model="jo_ai_video", last_asset_url="https://example.com/x.png")
        intent, confidence = main._detect_jo_chat_intent(payload, {})
        self.assertEqual(intent, "image_edit")
        self.assertGreaterEqual(confidence, 0.9)

    def test_animate_this_routes_to_image_to_video(self) -> None:
        payload = main.JOChatRequest(message="animate this", reference_image_url="https://example.com/x.png")
        intent, confidence = main._detect_jo_chat_intent(payload, {})
        self.assertEqual(intent, "image_to_video")
        self.assertGreaterEqual(confidence, 0.95)


class TestJOVideoJobLifecycle(unittest.TestCase):
    def test_job_progress_and_completion(self) -> None:
        main._JO_VIDEO_JOB_STORE.clear()
        job = main._new_jo_video_job(
            identity=None,
            model_id="jo_ai_video",
            prompt="cinematic walking scene",
            negative_prompt=None,
            settings_payload={"duration_seconds": 5},
            source_payload={"prompt": "cinematic walking scene"},
        )
        job_id = str(job["job_id"])

        main._update_jo_video_job_progress(
            job_id,
            JOAIVideoProgress(stage="image_generation", progress=0.4, message="Generating references."),
        )
        tracked = main._jo_video_job(job_id)
        self.assertIsNotNone(tracked)
        self.assertEqual(tracked["status"], "running")
        self.assertEqual(tracked["stage"], "image_generation")

        main._complete_jo_video_job(
            job_id,
            result=JOAIVideoResult(
                video_bytes=None,
                video_url="https://example.com/video.mp4",
                mime_type="video/mp4",
                output_format="mp4",
                provider_used="jo_ai_video_fallback",
                prompt_used="cinematic walking scene",
                negative_prompt_used="",
                seed_used=123,
                scene_prompts=["scene 1"],
                reference_images=[{"provider": "pollinations"}],
                progress_steps=[],
                metadata={},
            ),
            output_payload={"video_url": "https://example.com/video.mp4", "mime_type": "video/mp4"},
        )
        completed = main._jo_video_job(job_id)
        self.assertIsNotNone(completed)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["progress"], 1.0)
        self.assertEqual(completed["provider_used"], "jo_ai_video_fallback")


class TestJOVideoEngine(unittest.IsolatedAsyncioTestCase):
    @unittest.skipIf(getattr(jo_video_module, "Image", None) is None, "Pillow runtime is unavailable")
    async def test_fallback_engine_generates_gif(self) -> None:
        engine = JOAIVideoModelEngine(
            pollinations_service=_FakePollinationsService(),
            image_service=_FakeImageService(),
        )
        result = await engine.generate(
            JOAIVideoOptions(
                prompt="a person walking through a rainy city",
                aspect_ratio="9:16",
                duration_seconds=2,
                scene_count=1,
                output_format="gif",
                provider_level1_enabled=False,
                provider_model_order=("imagen-4",),
            )
        )
        self.assertEqual(result.provider_used, "jo_ai_video_fallback")
        self.assertEqual(result.output_format, "gif")
        self.assertEqual(result.mime_type, "image/gif")
        self.assertTrue(bool(result.video_bytes))
        self.assertGreaterEqual(len(result.reference_images), 1)

    @unittest.skipIf(getattr(jo_video_module, "Image", None) is None, "Pillow runtime is unavailable")
    async def test_local_image_service_fallback_when_provider_fails(self) -> None:
        engine = JOAIVideoModelEngine(
            pollinations_service=_FakePollinationsService(fail_image=True),
            image_service=_FakeImageService(),
        )
        result = await engine.generate(
            JOAIVideoOptions(
                prompt="a traveler in a mountain valley",
                aspect_ratio="16:9",
                duration_seconds=2,
                scene_count=1,
                output_format="gif",
                provider_level1_enabled=False,
                provider_model_order=("imagen-4",),
            )
        )
        self.assertTrue(bool(result.reference_images))
        self.assertEqual(result.reference_images[0].get("provider"), "local_image_service")

    @unittest.skipIf(getattr(jo_video_module, "Image", None) is None, "Pillow runtime is unavailable")
    async def test_fallback_disabled_requires_level1_output(self) -> None:
        class _NoLevel1(_FakePollinationsService):
            async def generate_video(self, **_kwargs):
                raise RuntimeError("level1 unavailable")

        engine = JOAIVideoModelEngine(
            pollinations_service=_NoLevel1(),
            image_service=_FakeImageService(),
        )
        with self.assertRaises(AIServiceError) as error_context:
            await engine.generate(
                JOAIVideoOptions(
                    prompt="city aerial motion",
                    aspect_ratio="9:16",
                    duration_seconds=2,
                    scene_count=1,
                    output_format="gif",
                    provider_level1_enabled=True,
                    fallback_enabled=False,
                )
            )
        self.assertIn("fallback engine is disabled", str(error_context.exception).lower())


if __name__ == "__main__":
    unittest.main()
