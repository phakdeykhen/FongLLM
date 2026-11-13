"""
MiniMind 多模态生成工具：让 LLM 通过 tool call 调用扩散模型生成图片/视频。
Image/video generation tools that MiniMind can call via <tool_call>.

模型在首次调用时懒加载（首次会从 HuggingFace 下载权重）。可用环境变量覆盖：
  MINIMIND_IMAGE_MODEL  默认 stabilityai/sdxl-turbo          (~7GB, 1-4 步出图)
  MINIMIND_VIDEO_MODEL  默认自动选择：
                        内存 <24GB 且无 CUDA → ByteDance/AnimateDiff-Lightning (+ SD1.5 底模, ~5GB, 4 步出片)
                        否则 → Wan-AI/Wan2.1-T2V-1.3B-Diffusers (~29GB; umT5-XXL 文本编码器单独就要 ~11GB 内存)
  MINIMIND_ANIMATEDIFF_BASE  AnimateDiff 使用的 SD1.5 底模，默认 emilianJR/epiCRealism
  MINIMIND_MEDIA_DIR    默认 <repo>/out/media
  MINIMIND_TRANSLATE_MODEL  默认 tencent/Hy-MT2-1.8B：非英文（如高棉语）提示词先翻译成英文再生成
"""
import os
import gc
import time
import threading
import torch

IMAGE_MODEL = os.environ.get("MINIMIND_IMAGE_MODEL", "stabilityai/sdxl-turbo")


def _total_ram_gb():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):
        return 0


VIDEO_MODEL = os.environ.get("MINIMIND_VIDEO_MODEL") or (
    "Wan-AI/Wan2.1-T2V-1.3B-Diffusers" if torch.cuda.is_available() or _total_ram_gb() >= 24
    else "ByteDance/AnimateDiff-Lightning")
TRANSLATE_MODEL = os.environ.get("MINIMIND_TRANSLATE_MODEL", "tencent/Hy-MT2-1.8B")
ANIMATEDIFF_BASE = os.environ.get("MINIMIND_ANIMATEDIFF_BASE", "emilianJR/epiCRealism")
MEDIA_DIR = os.environ.get("MINIMIND_MEDIA_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "out", "media")))

MEDIA_TOOLS = [
    {"type": "function", "function": {"name": "generate_image", "description": "Create a picture from a text description: images, photos, drawings, logos, icons, posters, PNGs. 根据文字描述生成一张图片", "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "图片内容的英文描述，如a cat sitting on the moon, digital art"}}, "required": ["prompt"]}}},
    {"type": "function", "function": {"name": "generate_video", "description": "根据文字描述生成一段几秒的短视频", "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "视频内容的英文描述，如a dog running on the beach at sunset"}}, "required": ["prompt"]}}},
]
MEDIA_TOOL_NAMES = {t["function"]["name"] for t in MEDIA_TOOLS}

_pipes = {}
_lock = threading.Lock()


def _device():
    if torch.cuda.is_available(): return "cuda"
    if torch.backends.mps.is_available(): return "mps"
    return "cpu"


def _dtype(device):
    return torch.float32 if device == "cpu" else (torch.bfloat16 if device == "cuda" else torch.float16)


def _unload_except(keep):
    # 16GB 统一内存放不下两个扩散模型，切换时释放另一个
    for k in [k for k in _pipes if k != keep]:
        del _pipes[k]
    gc.collect()
    if torch.backends.mps.is_available(): torch.mps.empty_cache()
    if torch.cuda.is_available(): torch.cuda.empty_cache()


def _get_image_pipe():
    if "image" not in _pipes:
        _unload_except("image")
        from diffusers import AutoPipelineForText2Image
        device = _device()
        kw = {"variant": "fp16"} if device != "cpu" and "sdxl" in IMAGE_MODEL else {}
        pipe = AutoPipelineForText2Image.from_pretrained(IMAGE_MODEL, torch_dtype=_dtype(device), **kw)
        pipe = pipe.to(device)
        if device != "cpu" and "sdxl" in IMAGE_MODEL.lower():
            pipe.vae.to(torch.float32)  # SDXL VAE 在 fp16 下溢出成 NaN → 全黑图，解码改用 fp32
        _pipes["image"] = pipe
    return _pipes["image"]


def _video_dtype(device):
    return torch.float32 if device == "cpu" else torch.bfloat16  # Wan is trained in bf16; fp16 risks overflow


def _encode_video_prompt(prompt, negative_prompt):
    """Stage 1: umT5-XXL text encoder (~11GB in bf16) runs alone on CPU, then is freed.
    Keeping it next to the video transformer needs ~15GB and thrashes a 16GB Mac."""
    from diffusers import WanPipeline
    _unload_except("none")
    enc = WanPipeline.from_pretrained(VIDEO_MODEL, transformer=None, vae=None, torch_dtype=torch.bfloat16)
    with torch.no_grad():
        pos, neg = enc.encode_prompt(prompt=prompt, negative_prompt=negative_prompt, do_classifier_free_guidance=True,
                                     max_sequence_length=512, device="cpu", dtype=torch.bfloat16)
    del enc
    gc.collect()
    return pos, neg


def _get_video_pipe():
    """Stage 2: transformer (1.3B) + VAE only (~3.5GB), cached between calls."""
    if "video" not in _pipes:
        _unload_except("video")
        from diffusers import AutoencoderKLWan, WanPipeline
        device = _device()
        vae = AutoencoderKLWan.from_pretrained(VIDEO_MODEL, subfolder="vae", torch_dtype=torch.float32)
        pipe = WanPipeline.from_pretrained(VIDEO_MODEL, vae=vae, text_encoder=None, tokenizer=None, torch_dtype=_video_dtype(device))
        if device == "mps":
            # default UniPC scheduler calls torch.linalg.solve, which MPS doesn't implement
            from diffusers import FlowMatchEulerDiscreteScheduler
            pipe.scheduler = FlowMatchEulerDiscreteScheduler(shift=3.0)
        _pipes["video"] = pipe.to(device)
    return _pipes["video"]


def _get_animatediff_pipe():
    """Light video model for 16GB machines: SD1.5 base + AnimateDiff-Lightning 4-step motion adapter."""
    if "video" not in _pipes:
        _unload_except("video")
        from diffusers import AnimateDiffPipeline, EulerDiscreteScheduler, MotionAdapter
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        device = _device()
        dtype = _dtype(device)
        adapter = MotionAdapter()
        adapter.load_state_dict(load_file(hf_hub_download(VIDEO_MODEL, "animatediff_lightning_4step_diffusers.safetensors")))
        pipe = AnimateDiffPipeline.from_pretrained(ANIMATEDIFF_BASE, motion_adapter=adapter.to(dtype), torch_dtype=dtype,
                                                   safety_checker=None, feature_extractor=None)
        pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, timestep_spacing="trailing", beta_schedule="linear")
        _pipes["video"] = pipe.to(device)
    return _pipes["video"]


def needs_translation(text):
    """True if the text has letters outside Latin scripts (Khmer, Thai, Chinese, ...)."""
    return any(ord(c) > 0x24F and c.isalpha() for c in text)


def _get_translator():
    if "translator" not in _pipes:
        from transformers import AutoModelForCausalLM, AutoTokenizer
        device = _device()
        tok = AutoTokenizer.from_pretrained(TRANSLATE_MODEL, fix_mistral_regex=True)
        # eager attention: torch 2.6 fused SDPA crashes on MPS with grouped-query attention
        model = AutoModelForCausalLM.from_pretrained(TRANSLATE_MODEL, dtype=_video_dtype(device), attn_implementation="eager")
        _pipes["translator"] = (model.to(device).eval(), tok)
    return _pipes["translator"]


def translate(text, target_language="English"):
    """Translate with Hy-MT2 (supports Khmer and ~30 other languages)."""
    with _lock:
        model, tok = _get_translator()
        msg = [{"role": "user", "content": f"Translate the following text into {target_language}. Note that you should "
                                           f"only output the translated result without any additional explanation:\n\n{text}"}]
        # transformers 4.57 returns a dict here, so ask for one and take the token ids
        ids = tok.apply_chat_template(msg, add_generation_prompt=True, return_tensors="pt", return_dict=True)["input_ids"].to(model.device)
        with torch.no_grad():
            out = model.generate(ids, max_new_tokens=max(64, len(text) * 2), do_sample=False, repetition_penalty=1.05)
        return tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()


def _out_path(kind, ext):
    os.makedirs(MEDIA_DIR, exist_ok=True)
    return os.path.join(MEDIA_DIR, f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.{ext}")


def _fit(image, longest=768):
    """Keep the photo's shape (a tall poster stays tall); sides must be multiples of 8."""
    w, h = image.size
    k = longest / max(w, h)
    return image.convert("RGB").resize((max(256, int(w * k) // 8 * 8), max(256, int(h * k) // 8 * 8)))


def generate_image(prompt, steps=None, width=512, height=512, progress=None, init_image=None, strength=0.6):
    """progress(floor, cap): reports how far along it is (0-1); the caller eases from floor toward cap.
    init_image (PIL): edit that picture instead of starting from noise (keeps its layout and colors)."""
    report = progress or (lambda floor, cap: None)
    with _lock:
        report(0.02, 0.35 if "image" not in _pipes else 0.1)
        pipe = _get_image_pipe()
        turbo = "turbo" in IMAGE_MODEL.lower() or "schnell" in IMAGE_MODEL.lower()
        kw = {"guidance_scale": 0.0} if turbo else {}
        if init_image is not None:
            from diffusers import AutoPipelineForImage2Image
            pipe = AutoPipelineForImage2Image.from_pipe(pipe)   # same weights, no extra memory
            init_image = _fit(init_image)
            # turbo img2img runs steps*strength denoising steps, which must be >= 1
            steps = steps or (4 if turbo else 30)
            kw.update(image=init_image, strength=strength)
            width, height = init_image.size
        else:
            steps = steps or (2 if turbo else 30)
            kw.update(width=width, height=height)
        st = time.time()
        report(0.35, 0.45)

        def on_step(p, i, t, cb_kwargs):
            done = min(1, (i + 1) / max(1, getattr(p, "_num_timesteps", None) or steps))
            report(0.35 + 0.5 * done, min(0.85, 0.5 + 0.5 * done))
            return cb_kwargs
        kw["callback_on_step_end"] = on_step
        if pipe.vae.dtype == torch.float32 and pipe.unet.dtype != torch.float32:
            latents = pipe(prompt=prompt, num_inference_steps=steps, output_type="latent", **kw).images
            report(0.85, 0.97)
            pipe.vae.to(torch.float32)   # img2img casts the VAE back to fp16 after encoding the photo
            with torch.no_grad():
                decoded = pipe.vae.decode(latents.float() / pipe.vae.config.scaling_factor).sample
            image = pipe.image_processor.postprocess(decoded, output_type="pil")[0]
        else:
            image = pipe(prompt=prompt, num_inference_steps=steps, **kw).images[0]
        path = _out_path("image", "png")
        image.save(path)
        report(1.0, 1.0)
    return {"type": "image", "path": path, "prompt": prompt, "seconds": round(time.time() - st, 1)}


def generate_video(prompt, num_frames=33, steps=25, width=480, height=320, fps=16):
    # num_frames 需为 4k+1；33 帧 ≈ 2 秒。MPS 上 1.3B 模型每段约数分钟
    from diffusers.utils import export_to_video
    if "animatediff" in VIDEO_MODEL.lower():
        with _lock:
            pipe = _get_animatediff_pipe()
            st = time.time()
            frames = pipe(prompt=prompt, negative_prompt="blurry, low quality, distorted", guidance_scale=1.0,
                          num_inference_steps=4, num_frames=8, width=256, height=256).frames[0]  # 16GB Mac: 512x512x16 ran out of memory
            path = _out_path("video", "mp4")
            export_to_video(frames, path, fps=8)
        return {"type": "video", "path": path, "prompt": prompt, "seconds": round(time.time() - st, 1)}
    with _lock:
        st = time.time()
        _pipes.pop("video", None)  # free stage 2 while the big text encoder runs
        pos, neg = _encode_video_prompt(prompt, "blurry, low quality, distorted, static")
        pipe = _get_video_pipe()
        device, dtype = _device(), _video_dtype(_device())
        frames = pipe(prompt_embeds=pos.to(device, dtype), negative_prompt_embeds=neg.to(device, dtype),
                      height=height, width=width, num_frames=num_frames,
                      num_inference_steps=steps, guidance_scale=5.0).frames[0]
        path = _out_path("video", "mp4")
        export_to_video(frames, path, fps=fps)
    return {"type": "video", "path": path, "prompt": prompt, "seconds": round(time.time() - st, 1)}


def execute_media_tool(name, args, progress=None, init_image=None):
    """Returns a JSON-serializable result dict, or None if `name` is not a media tool.
    progress / init_image: see generate_image (images only)."""
    if name not in MEDIA_TOOL_NAMES:
        return None
    prompt = (args or {}).get("prompt") or (args or {}).get("text") or ""
    if not prompt.strip():
        return {"error": "prompt 不能为空"}
    try:
        original = prompt
        if needs_translation(prompt):
            prompt = translate(prompt)  # image/video text encoders only understand English well
        result = (generate_image(prompt, progress=progress, init_image=init_image) if name == "generate_image"
                  else generate_video(prompt))
        if original != prompt:
            result["original_prompt"] = original
        return result
    except Exception as e:
        return {"error": f"{name} 失败: {str(e)[:200]}"}


if __name__ == "__main__":
    import argparse, json
    p = argparse.ArgumentParser(description="直接测试图片/视频生成")
    p.add_argument("kind", choices=["image", "video"])
    p.add_argument("prompt")
    a = p.parse_args()
    print(json.dumps(execute_media_tool(f"generate_{a.kind}", {"prompt": a.prompt}), ensure_ascii=False, indent=2))
