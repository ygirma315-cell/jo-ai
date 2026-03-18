from __future__ import annotations

import asyncio
import hashlib
import io
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

import aiohttp

from bot.services.ai_service import (
    AIServiceError,
    GeneratedImageResult,
    GeneratedVideoResult,
    ImageGenerationService,
    PollinationsMediaService,
    build_enhanced_image_prompt,
    build_enhanced_video_prompt,
)

try:
    from PIL import Image, ImageChops
except Exception:  # pragma: no cover - optional dependency at runtime
    Image = None  # type: ignore[assignment]
    ImageChops = None  # type: ignore[assignment]

ProgressCallback = Callable[["JOAIVideoProgress"], Awaitable[None] | None]
MotionStrength = Literal["low", "medium", "high"]
VideoQuality = Literal["low", "medium", "high"]
OutputFormat = Literal["mp4", "gif", "webm"]


@dataclass(slots=True)
class JOAIVideoProgress:
    stage: str
    progress: float
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class JOAIVideoOptions:
    prompt: str
    negative_prompt: str | None = None
    aspect_ratio: Literal["16:9", "9:16"] = "9:16"
    duration_seconds: int = 5
    scene_count: int = 1
    motion_strength: MotionStrength = "medium"
    camera_motion: str = "cinematic"
    style: str | None = None
    quality: VideoQuality = "high"
    seed: int | None = None
    fps: int = 24
    output_format: OutputFormat = "mp4"
    reference_image_url: str | None = None
    reference_image_bytes: bytes | None = None
    provider_order: tuple[str, ...] = ("pollinations", "local")
    provider_model_order: tuple[str, ...] = ("imagen-4", "flux-2-dev", "dirtberry-pro")
    provider_level1_enabled: bool = False
    provider_level1_model: str | None = None
    fallback_enabled: bool = True

    def normalized_seed(self) -> int:
        if isinstance(self.seed, int):
            return max(1, self.seed)
        digest = hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()[:10]
        return max(1, int(digest, 16))

    def safe_duration(self, max_seconds: int = 10) -> int:
        return max(1, min(max_seconds, int(self.duration_seconds or 5)))

    def safe_scene_count(self, max_scenes: int = 4) -> int:
        duration_hint = max(1, math.ceil(self.safe_duration() / 3))
        requested = max(1, int(self.scene_count or duration_hint))
        return max(1, min(max_scenes, requested))

    def safe_fps(self) -> int:
        return max(8, min(30, int(self.fps or 24)))


@dataclass(slots=True)
class ScenePlan:
    index: int
    prompt: str
    duration_seconds: float


@dataclass(slots=True)
class ReferenceImageCandidate:
    scene_index: int
    provider: str
    model: str
    prompt: str
    image_bytes: bytes
    image_url: str | None
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class JOAIVideoResult:
    video_bytes: bytes | None
    video_url: str | None
    mime_type: str
    output_format: str
    provider_used: str
    prompt_used: str
    negative_prompt_used: str
    seed_used: int
    scene_prompts: list[str]
    reference_images: list[dict[str, Any]]
    progress_steps: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


class JOAIVideoModelEngine:
    def __init__(
        self,
        *,
        pollinations_service: PollinationsMediaService,
        image_service: ImageGenerationService | None = None,
    ) -> None:
        self._pollinations_service = pollinations_service
        self._image_service = image_service

    async def generate(
        self,
        options: JOAIVideoOptions,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> JOAIVideoResult:
        if Image is None:
            raise AIServiceError("JO AI Video Model renderer is unavailable.")

        progress_log: list[dict[str, Any]] = []

        async def emit(stage: str, progress: float, message: str, metadata: dict[str, Any] | None = None) -> None:
            payload = JOAIVideoProgress(
                stage=stage,
                progress=max(0.0, min(1.0, progress)),
                message=message,
                metadata=dict(metadata or {}),
            )
            progress_log.append(
                {
                    "stage": payload.stage,
                    "progress": payload.progress,
                    "message": payload.message,
                    "metadata": payload.metadata,
                }
            )
            if progress_callback is None:
                return
            maybe_awaitable = progress_callback(payload)
            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable

        await emit("prompt_enhancer", 0.06, "Understanding prompt and cinematic intent.")
        enhanced_prompt, negative_prompt = self._enhance_prompt(options)

        await emit("scene_planner", 0.14, "Planning scenes with continuity locks.")
        scenes = self._plan_scenes(enhanced_prompt, options)

        if options.provider_level1_enabled and not options.reference_image_url and not options.reference_image_bytes:
            await emit("master_engine", 0.24, "Trying provider-backed level 1 rendering path.")
            level1_result = await self._try_provider_level1(options, enhanced_prompt)
            if level1_result is not None:
                await emit("result_formatter", 0.99, "Provider video generated successfully.")
                return JOAIVideoResult(
                    video_bytes=level1_result.video_bytes,
                    video_url=level1_result.video_url,
                    mime_type=level1_result.mime_type or "video/mp4",
                    output_format=self._format_from_mime(level1_result.mime_type or "video/mp4"),
                    provider_used="provider_level1",
                    prompt_used=enhanced_prompt,
                    negative_prompt_used=negative_prompt,
                    seed_used=options.normalized_seed(),
                    scene_prompts=[scene.prompt for scene in scenes],
                    reference_images=[],
                    progress_steps=progress_log,
                    metadata={"fallback_used": False, "level": 1},
                )
            await emit("master_engine", 0.29, "Provider level 1 was unavailable, switching to fallback engine.")
        elif options.provider_level1_enabled:
            await emit("master_engine", 0.24, "Skipping level 1 provider because a reference image is locked.")

        if not options.fallback_enabled:
            raise AIServiceError(
                "JO AI Video Model fallback engine is disabled and no level 1 provider output was available."
            )

        await emit("image_adapter", 0.34, "Generating scene reference images.")
        selected_images = await self._generate_reference_images(
            scenes=scenes,
            options=options,
            negative_prompt=negative_prompt,
            emit=emit,
        )
        if not selected_images:
            raise AIServiceError("JO AI Video Model could not produce reference images.")

        await emit("consistency", 0.64, "Applying style and identity consistency locks.")
        selected_images = self._apply_consistency_lock(selected_images, options)

        await emit("motion_engine", 0.74, "Animating references into coherent motion frames.")
        frames = self._compose_motion_frames(selected_images, options)
        if not frames:
            raise AIServiceError("JO AI Video Model did not produce animation frames.")

        await emit("renderer", 0.88, "Rendering final video output.")
        video_bytes, mime_type, output_format = self._render_output(frames, options)

        await emit("result_formatter", 1.0, "Final video is ready.")
        return JOAIVideoResult(
            video_bytes=video_bytes,
            video_url=None,
            mime_type=mime_type,
            output_format=output_format,
            provider_used="jo_ai_video_fallback",
            prompt_used=enhanced_prompt,
            negative_prompt_used=negative_prompt,
            seed_used=options.normalized_seed(),
            scene_prompts=[scene.prompt for scene in scenes],
            reference_images=[
                {
                    "scene_index": candidate.scene_index,
                    "provider": candidate.provider,
                    "model": candidate.model,
                    "score": round(candidate.score, 4),
                    "image_url": candidate.image_url,
                    "metadata": candidate.metadata,
                }
                for candidate in selected_images
            ],
            progress_steps=progress_log,
            metadata={
                "fallback_used": True,
                "level": 2,
                "frame_count": len(frames),
                "fps": options.safe_fps(),
            },
        )

    def _enhance_prompt(self, options: JOAIVideoOptions) -> tuple[str, str]:
        raw_prompt = " ".join(str(options.prompt or "").split())
        if not raw_prompt:
            raise AIServiceError("Video prompt is required.")

        style_hint = str(options.style or "").strip()
        camera_hint = str(options.camera_motion or "cinematic").strip()
        quality_hint = str(options.quality or "high").strip()
        enhanced = (
            build_enhanced_video_prompt(
                raw_prompt,
                aspect_ratio=options.aspect_ratio,
                duration_seconds=options.safe_duration(),
            )
            or raw_prompt
        )

        if len(raw_prompt.split()) <= 6:
            enhanced = (
                f"{enhanced}, clear subject identity, rich environment, cinematic lighting, "
                "stable framing, realistic textures, directional movement."
            )

        if style_hint:
            enhanced = f"{enhanced}, style preset: {style_hint}."
        if camera_hint:
            enhanced = f"{enhanced}, camera motion profile: {camera_hint}."
        if quality_hint:
            enhanced = f"{enhanced}, quality target: {quality_hint}."

        negative_prompt = " ".join(str(options.negative_prompt or "").split())
        if not negative_prompt:
            negative_prompt = (
                "blurry, low resolution, watermark, duplicated face, extra limbs, broken anatomy, "
                "flicker, distorted perspective, inconsistent clothing"
            )
        return enhanced.strip(), negative_prompt

    def _plan_scenes(self, enhanced_prompt: str, options: JOAIVideoOptions) -> list[ScenePlan]:
        scene_count = options.safe_scene_count()
        safe_duration = options.safe_duration()
        per_scene = safe_duration / max(1, scene_count)
        beats = (
            "establishing frame with calm setup",
            "subject motion progression with directional intent",
            "cinematic emphasis beat with stronger perspective",
            "closing frame with a clean final composition",
        )
        scenes: list[ScenePlan] = []
        continuity = (
            "Preserve subject identity, outfit, environment tone, color palette, and composition continuity."
        )
        for index in range(scene_count):
            beat = beats[index] if index < len(beats) else beats[-1]
            scene_prompt = (
                f"{enhanced_prompt}\n\n"
                f"Scene {index + 1}/{scene_count}: {beat}. {continuity}"
            )
            scenes.append(ScenePlan(index=index, prompt=scene_prompt, duration_seconds=per_scene))
        return scenes

    async def _try_provider_level1(
        self,
        options: JOAIVideoOptions,
        enhanced_prompt: str,
    ) -> GeneratedVideoResult | None:
        try:
            return await self._pollinations_service.generate_video(
                prompt=enhanced_prompt,
                model=(options.provider_level1_model or "").strip() or None,
                duration_seconds=options.safe_duration(),
                aspect_ratio=options.aspect_ratio,
                enhance=True,
                audio=False,
            )
        except Exception:
            return None

    async def _generate_reference_images(
        self,
        *,
        scenes: list[ScenePlan],
        options: JOAIVideoOptions,
        negative_prompt: str,
        emit: Callable[[str, float, str, dict[str, Any] | None], Awaitable[None]],
    ) -> list[ReferenceImageCandidate]:
        width, height = self._dimensions_from_ratio(options.aspect_ratio)
        image_size = f"{width}x{height}"
        selected: list[ReferenceImageCandidate] = []
        previous_best: ReferenceImageCandidate | None = None
        provider_order = tuple(str(item or "").strip().lower() for item in options.provider_order if str(item or "").strip())
        if not provider_order:
            provider_order = ("pollinations", "local")

        for scene in scenes:
            scene_progress = 0.36 + ((scene.index + 1) / max(1, len(scenes)) * 0.24)
            await emit(
                "image_generation_adapter",
                scene_progress,
                f"Generating reference candidates for scene {scene.index + 1}.",
                {"scene_index": scene.index},
            )
            candidates: list[ReferenceImageCandidate] = []
            prompt_with_negative = f"{scene.prompt}\n\nNegative prompt: {negative_prompt}"
            prompt_with_seed = f"{prompt_with_negative}\n\nContinuity seed: {options.normalized_seed()}"

            if scene.index == 0:
                source_candidate = await self._candidate_from_reference_source(
                    scene_index=scene.index,
                    scene_prompt=prompt_with_seed,
                    options=options,
                    width=width,
                    height=height,
                )
                if source_candidate is not None:
                    candidates.append(source_candidate)

            for provider in provider_order:
                if len(candidates) >= 3:
                    break

                if provider in {"pollinations", "provider"}:
                    for model_name in options.provider_model_order:
                        model = str(model_name or "").strip()
                        if not model:
                            continue
                        generated = await self._try_generate_pollinations_candidate(
                            prompt=prompt_with_seed,
                            model=model,
                            size=image_size,
                            quality=options.quality,
                            reference_url=options.reference_image_url if scene.index == 0 else None,
                        )
                        if generated is None:
                            continue
                        score = self._score_candidate(
                            generated.image_bytes,
                            width=width,
                            height=height,
                            previous_image=(previous_best.image_bytes if previous_best is not None else None),
                        )
                        candidates.append(
                            ReferenceImageCandidate(
                                scene_index=scene.index,
                                provider="pollinations",
                                model=model,
                                prompt=prompt_with_seed,
                                image_bytes=generated.image_bytes,
                                image_url=generated.image_url,
                                score=score,
                                metadata={"size": image_size},
                            )
                        )
                        if len(candidates) >= 3:
                            break
                    continue

                if provider in {"local", "jo_ai", "image_service"} and self._image_service is not None:
                    generated = await self._try_generate_local_candidate(
                        prompt=build_enhanced_image_prompt(prompt_with_seed, ratio=options.aspect_ratio) or prompt_with_seed,
                        size=image_size,
                        ratio=options.aspect_ratio,
                    )
                    if generated is None or not generated.image_bytes:
                        continue
                    score = self._score_candidate(
                        generated.image_bytes,
                        width=width,
                        height=height,
                        previous_image=(previous_best.image_bytes if previous_best is not None else None),
                    )
                    candidates.append(
                        ReferenceImageCandidate(
                            scene_index=scene.index,
                            provider="local_image_service",
                            model="jo_ai_image_generate",
                            prompt=prompt_with_seed,
                            image_bytes=generated.image_bytes,
                            image_url=generated.image_url,
                            score=score,
                            metadata={"size": image_size},
                        )
                    )

            if not candidates:
                continue
            candidates.sort(key=lambda item: item.score, reverse=True)
            best = candidates[0]
            selected.append(best)
            previous_best = best

            await emit(
                "best_image_selector",
                min(0.62, scene_progress + 0.02),
                f"Selected best reference for scene {scene.index + 1}.",
                {
                    "scene_index": scene.index,
                    "provider": best.provider,
                    "model": best.model,
                    "score": round(best.score, 4),
                },
            )

        return selected

    async def _candidate_from_reference_source(
        self,
        *,
        scene_index: int,
        scene_prompt: str,
        options: JOAIVideoOptions,
        width: int,
        height: int,
    ) -> ReferenceImageCandidate | None:
        payload = bytes(options.reference_image_bytes or b"")
        if not payload and options.reference_image_url:
            payload = await _download_binary(options.reference_image_url)
        if not payload:
            return None
        score = self._score_candidate(payload, width=width, height=height, previous_image=None)
        return ReferenceImageCandidate(
            scene_index=scene_index,
            provider="reference_lock",
            model="reference_image",
            prompt=scene_prompt,
            image_bytes=payload,
            image_url=options.reference_image_url,
            score=score + 0.1,
            metadata={"reference_lock": True},
        )

    async def _try_generate_pollinations_candidate(
        self,
        *,
        prompt: str,
        model: str,
        size: str,
        quality: VideoQuality,
        reference_url: str | None,
    ) -> GeneratedImageResult | None:
        if not str(self._pollinations_service.api_key or "").strip():
            return None
        try:
            generated = await self._pollinations_service.generate_image(
                prompt=prompt,
                model=model,
                size=size,
                enhance=True,
                image=reference_url,
                quality=quality,
            )
            if generated.image_bytes:
                return generated
            if generated.image_url:
                return GeneratedImageResult(
                    image_bytes=await _download_binary(generated.image_url),
                    image_url=generated.image_url,
                )
            return None
        except Exception:
            return None

    async def _try_generate_local_candidate(
        self,
        *,
        prompt: str,
        size: str,
        ratio: Literal["16:9", "9:16"],
    ) -> GeneratedImageResult | None:
        if self._image_service is None:
            return None
        try:
            return await self._image_service.generate_image(prompt=prompt, size=size, ratio=ratio)
        except Exception:
            return None

    def _score_candidate(
        self,
        image_bytes: bytes,
        *,
        width: int,
        height: int,
        previous_image: bytes | None,
    ) -> float:
        if Image is None:
            return 0.0
        try:
            with Image.open(io.BytesIO(image_bytes)) as raw:
                image = raw.convert("RGB")
                w, h = image.size
                resolution_score = min(1.0, (w * h) / max(1.0, width * height))
                center_crop = image.crop(
                    (
                        int(w * 0.2),
                        int(h * 0.2),
                        int(w * 0.8),
                        int(h * 0.8),
                    )
                )
                histogram = center_crop.histogram()
                mean_hist = (sum(histogram) / max(1, len(histogram))) if histogram else 0.0
                detail_score = min(1.0, mean_hist / 250.0) if mean_hist > 0 else 0.0
                continuity_score = 0.5
                if previous_image and ImageChops is not None:
                    with Image.open(io.BytesIO(previous_image)) as previous_raw:
                        prev = previous_raw.convert("RGB").resize((w, h), Image.Resampling.BILINEAR)
                        diff = ImageChops.difference(image, prev)
                        stat = sum(diff.histogram()) / max(1, len(diff.histogram()))
                        continuity_score = max(0.0, min(1.0, 1.0 - (stat / 512.0)))
                return (resolution_score * 0.45) + (detail_score * 0.2) + (continuity_score * 0.35)
        except Exception:
            return 0.0

    def _apply_consistency_lock(
        self,
        candidates: list[ReferenceImageCandidate],
        options: JOAIVideoOptions,
    ) -> list[ReferenceImageCandidate]:
        if not candidates:
            return []
        locked_seed = options.normalized_seed()
        for candidate in candidates:
            candidate.metadata["locked_seed"] = locked_seed
            candidate.metadata["camera_motion"] = options.camera_motion
            candidate.metadata["motion_strength"] = options.motion_strength
        return candidates

    def _compose_motion_frames(
        self,
        candidates: list[ReferenceImageCandidate],
        options: JOAIVideoOptions,
    ) -> list["Image.Image"]:
        if Image is None:
            return []
        width, height = self._dimensions_from_ratio(options.aspect_ratio)
        total_frames = max(12, options.safe_duration() * options.safe_fps())
        source_images: list["Image.Image"] = []
        for candidate in candidates:
            with Image.open(io.BytesIO(candidate.image_bytes)) as raw:
                source_images.append(self._resize_cover(raw.convert("RGB"), width, height))
        if not source_images:
            return []

        if len(source_images) == 1:
            source_images.append(source_images[0])

        segments = len(source_images) - 1
        frames_per_segment = max(6, total_frames // max(1, segments))
        extra = max(0, total_frames - (frames_per_segment * segments))

        frames: list["Image.Image"] = []
        for index in range(segments):
            segment_frame_count = frames_per_segment + (1 if index < extra else 0)
            composed = self._compose_segment(
                first=source_images[index],
                second=source_images[index + 1],
                width=width,
                height=height,
                frame_count=segment_frame_count,
                segment_index=index,
                segment_total=segments,
                motion_strength=options.motion_strength,
                camera_motion=options.camera_motion,
            )
            if index > 0 and composed:
                composed = composed[1:]
            frames.extend(composed)
        return frames

    def _compose_segment(
        self,
        *,
        first: "Image.Image",
        second: "Image.Image",
        width: int,
        height: int,
        frame_count: int,
        segment_index: int,
        segment_total: int,
        motion_strength: MotionStrength,
        camera_motion: str,
    ) -> list["Image.Image"]:
        motion_scale = {"low": 0.045, "medium": 0.075, "high": 0.11}.get(motion_strength, 0.075)
        cinematic_bias = 1.0 if "cinematic" in str(camera_motion or "").lower() else 0.85
        segment_bias = max(0, min(segment_index, max(0, segment_total - 1)))
        reverse_pan = bool(segment_bias % 2)
        frames: list["Image.Image"] = []
        total = max(4, int(frame_count))

        for index in range(total):
            t = index / max(1, total - 1)
            blend = Image.blend(first, second, t)
            zoom = 1.0 + (motion_scale * cinematic_bias * t) + (0.012 * segment_bias)
            resized = blend.resize(
                (max(width, int(width * zoom)), max(height, int(height * zoom))),
                Image.Resampling.LANCZOS,
            )
            max_x = max(0, resized.width - width)
            max_y = max(0, resized.height - height)
            if reverse_pan:
                x = int(max_x * (1.0 - t))
                y = int(max_y * t)
            else:
                x = int(max_x * t)
                y = int(max_y * (1.0 - t))
            frame = resized.crop((x, y, x + width, y + height))
            frames.append(frame.convert("RGB"))
        return frames

    def _render_output(
        self,
        frames: list["Image.Image"],
        options: JOAIVideoOptions,
    ) -> tuple[bytes, str, str]:
        desired = str(options.output_format or "mp4").strip().lower()
        if desired == "webm":
            webm_bytes = self._render_ffmpeg(frames, fps=options.safe_fps(), target="webm")
            if webm_bytes:
                return webm_bytes, "video/webm", "webm"
        if desired == "mp4":
            mp4_bytes = self._render_ffmpeg(frames, fps=options.safe_fps(), target="mp4")
            if mp4_bytes:
                return mp4_bytes, "video/mp4", "mp4"
        gif_bytes = self._render_gif(frames, fps=options.safe_fps())
        return gif_bytes, "image/gif", "gif"

    def _render_ffmpeg(
        self,
        frames: list["Image.Image"],
        *,
        fps: int,
        target: Literal["mp4", "webm"],
    ) -> bytes | None:
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            return None
        with tempfile.TemporaryDirectory(prefix="jo_ai_video_") as temp_dir:
            temp_path = Path(temp_dir)
            for index, frame in enumerate(frames):
                frame.save(temp_path / f"frame_{index:05d}.png", format="PNG")
            output_path = temp_path / ("video.mp4" if target == "mp4" else "video.webm")

            if target == "mp4":
                command = [
                    ffmpeg_bin,
                    "-y",
                    "-framerate",
                    str(max(8, min(30, fps))),
                    "-i",
                    str(temp_path / "frame_%05d.png"),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ]
            else:
                command = [
                    ffmpeg_bin,
                    "-y",
                    "-framerate",
                    str(max(8, min(30, fps))),
                    "-i",
                    str(temp_path / "frame_%05d.png"),
                    "-c:v",
                    "libvpx-vp9",
                    "-b:v",
                    "0",
                    "-crf",
                    "36",
                    str(output_path),
                ]

            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    timeout=90,
                )
            except Exception:
                return None
            if completed.returncode != 0 or not output_path.exists():
                return None
            payload = output_path.read_bytes()
            return payload if payload else None

    def _render_gif(self, frames: list["Image.Image"], *, fps: int) -> bytes:
        output = io.BytesIO()
        duration_ms = max(30, int(1000 / max(1, fps)))
        converted = [frame.convert("P", palette=Image.ADAPTIVE) for frame in frames]
        converted[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=converted[1:],
            duration=duration_ms,
            loop=0,
            optimize=False,
        )
        return output.getvalue()

    def _resize_cover(self, image: "Image.Image", width: int, height: int) -> "Image.Image":
        source_w, source_h = image.size
        if source_w <= 0 or source_h <= 0:
            return image.resize((width, height), Image.Resampling.LANCZOS)
        scale = max(width / source_w, height / source_h)
        resized = image.resize(
            (max(1, int(source_w * scale)), max(1, int(source_h * scale))),
            Image.Resampling.LANCZOS,
        )
        left = max(0, (resized.width - width) // 2)
        top = max(0, (resized.height - height) // 2)
        return resized.crop((left, top, left + width, top + height))

    def _dimensions_from_ratio(self, ratio: str) -> tuple[int, int]:
        return (576, 1024) if str(ratio).strip() == "9:16" else (1024, 576)

    def _format_from_mime(self, mime: str) -> str:
        normalized = str(mime or "").strip().lower()
        if "webm" in normalized:
            return "webm"
        if "gif" in normalized:
            return "gif"
        return "mp4"


async def _download_binary(url: str) -> bytes:
    target = str(url or "").strip()
    if not target:
        return b""
    timeout = aiohttp.ClientTimeout(total=50)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(target) as response:
            if response.status >= 400:
                return b""
            return await response.read()
