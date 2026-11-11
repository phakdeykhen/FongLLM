"""
MiniMind 多模态生成工具：让 LLM 通过 tool call 调用扩散模型生成图片/视频。
Image/video generation tools that MiniMind can call via <tool_call>.

模型在首次调用时懒加载（首次会从 HuggingFace 下载权重）。可用环境变量覆盖：
  MINIMIND_IMAGE_MODEL  默认 stabilityai/sdxl-turbo          (~7GB, 1-4 步出图)
  MINIMIND_VIDEO_MODEL  默认 Wan-AI/Wan2.1-T2V-1.3B-Diffusers (~17GB 下载, 16GB 内存可跑)
  MINIMIND_MEDIA_DIR    默认 <repo>/out/media
"""
import os
import gc
import time
import threading
import torch

IMAGE_MODEL = os.environ.get("MINIMIND_IMAGE_MODEL", "stabilityai/sdxl-turbo")
VIDEO_MODEL = os.environ.get("MINIMIND_VIDEO_MODEL", "Wan-AI/Wan2.1-T2V-1.3B-Diffusers")
MEDIA_DIR = os.environ.get("MINIMIND_MEDIA_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "out", "media")))

MEDIA_TOOLS = [
    {"type": "function", "function": {"name": "generate_image", "description": "根据文字描述生成一张图片", "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "图片内容的英文描述，如a cat sitting on the moon, digital art"}}, "required": ["prompt"]}}},
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
        if device == "mps": pipe.enable_attention_slicing()
        _pipes["image"] = pipe.to(device)
    return _pipes["image"]


def _get_video_pipe():
    if "video" not in _pipes:
        _unload_except("video")
        from diffusers import AutoencoderKLWan, WanPipeline
        device = _device()
        dtype = torch.bfloat16 if device == "cuda" else (torch.float16 if device == "mps" else torch.float32)
        vae = AutoencoderKLWan.from_pretrained(VIDEO_MODEL, subfolder="vae", torch_dtype=torch.float32)
        pipe = WanPipeline.from_pretrained(VIDEO_MODEL, vae=vae, torch_dtype=dtype)
        _pipes["video"] = pipe.to(device)
    return _pipes["video"]


def _out_path(kind, ext):
    os.makedirs(MEDIA_DIR, exist_ok=True)
    return os.path.join(MEDIA_DIR, f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.{ext}")


def generate_image(prompt, steps=None, width=512, height=512):
    with _lock:
        pipe = _get_image_pipe()
        turbo = "turbo" in IMAGE_MODEL.lower() or "schnell" in IMAGE_MODEL.lower()
        steps = steps or (2 if turbo else 30)
        kw = {"guidance_scale": 0.0} if turbo else {}
        st = time.time()
        image = pipe(prompt=prompt, num_inference_steps=steps, width=width, height=height, **kw).images[0]
        path = _out_path("image", "png")
        image.save(path)
    return {"type": "image", "path": path, "prompt": prompt, "seconds": round(time.time() - st, 1)}


def generate_video(prompt, num_frames=33, steps=25, width=480, height=320, fps=16):
    # num_frames 需为 4k+1；33 帧 ≈ 2 秒。MPS 上 1.3B 模型每段约数分钟
    from diffusers.utils import export_to_video
    with _lock:
        pipe = _get_video_pipe()
        st = time.time()
        frames = pipe(prompt=prompt, negative_prompt="blurry, low quality, distorted, static",
                      height=height, width=width, num_frames=num_frames,
                      num_inference_steps=steps, guidance_scale=5.0).frames[0]
        path = _out_path("video", "mp4")
        export_to_video(frames, path, fps=fps)
    return {"type": "video", "path": path, "prompt": prompt, "seconds": round(time.time() - st, 1)}


def execute_media_tool(name, args):
    """Returns a JSON-serializable result dict, or None if `name` is not a media tool."""
    if name not in MEDIA_TOOL_NAMES:
        return None
    prompt = (args or {}).get("prompt") or (args or {}).get("text") or ""
    if not prompt.strip():
        return {"error": "prompt 不能为空"}
    try:
        return generate_image(prompt) if name == "generate_image" else generate_video(prompt)
    except Exception as e:
        return {"error": f"{name} 失败: {str(e)[:200]}"}


if __name__ == "__main__":
    import argparse, json
    p = argparse.ArgumentParser(description="直接测试图片/视频生成")
    p.add_argument("kind", choices=["image", "video"])
    p.add_argument("prompt")
    a = p.parse_args()
    print(json.dumps(execute_media_tool(f"generate_{a.kind}", {"prompt": a.prompt}), ensure_ascii=False, indent=2))
