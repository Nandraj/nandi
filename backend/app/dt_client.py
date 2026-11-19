"""Draw Things gRPC client (ImageGenerationService, default port 7859).

Builds the GenerationConfiguration FlatBuffer by hand (slot numbers follow the
field order of Draw Things' config.fbs), encodes init images as Draw Things
tensors and decodes returned frames.
"""
from __future__ import annotations

import random
import ssl
import struct
import threading
from typing import Callable, Iterable, Optional

import flatbuffers
import grpc
import numpy as np
from PIL import Image

from .pb import imageService_pb2 as pb
from .pb import imageService_pb2_grpc as pbg

HDR = 68
FPZIP_ID = 0xF7217
CCV_CPU, NHWC, CCV_16F = 1, 2, 0x20000

SAMPLERS = {
    "DPMPP2MKarras": 0, "EulerA": 1, "DDIM": 2, "PLMS": 3, "DPMPPSDEKarras": 4,
    "UniPC": 5, "LCM": 6, "EulerASubstep": 7, "DPMPPSDESubstep": 8, "TCD": 9,
    "EulerATrailing": 10, "DPMPPSDETrailing": 11, "DPMPP2MAYS": 12, "EulerAAYS": 13,
    "DPMPPSDEAYS": 14, "DPMPP2MTrailing": 15, "DDIMTrailing": 16, "UniPCTrailing": 17,
    "UniPCAYS": 18, "TCDTrailing": 19,
}


class GenerationCancelled(Exception):
    pass


# ---------------------------------------------------------------- config

# Advanced GenerationConfiguration fields: name -> (FlatBuffer slot, kind, schema default).
# Slots are the 0-based position in Draw Things' config.fbs. kinds: f float, u uint32, i int32,
# b bool, s string, h ushort, w ushort holding pixels/64, B ubyte.
ADV_FIELDS: dict[str, tuple] = {
    "hires_fix": (11, "b", False), "hires_fix_start_width": (12, "w", 0), "hires_fix_start_height": (13, "w", 0),
    "hires_fix_strength": (14, "f", 0.7), "upscaler": (15, "s", ""), "upscaler_scale_factor": (63, "B", 0),
    "image_guidance_scale": (16, "f", 1.5), "face_restoration": (22, "s", ""), "clip_weight": (25, "f", 1.0),
    "zero_negative_prompt": (37, "b", False), "fps_id": (42, "u", 5), "motion_bucket_id": (43, "u", 127),
    "cond_aug": (44, "f", 0.02), "start_frame_cfg": (45, "f", 1.0), "sharpness": (48, "f", 0.0),
    "stage_2_steps": (50, "u", 10), "stage_2_cfg": (51, "f", 1.0), "stage_2_shift": (52, "f", 1.0),
    "tiled_decoding": (53, "b", False), "decoding_tile_width": (54, "h", 10), "decoding_tile_height": (55, "h", 10),
    "decoding_tile_overlap": (56, "h", 2), "stochastic_sampling_gamma": (57, "f", 0.3),
    "tiled_diffusion": (59, "b", False), "diffusion_tile_width": (60, "h", 16), "diffusion_tile_height": (61, "h", 16),
    "diffusion_tile_overlap": (62, "h", 2), "t5_text_encoder": (64, "b", True),
    "speed_up_with_guidance_embed": (69, "b", True), "guidance_embed": (70, "f", 3.5),
    "resolution_dependent_shift": (71, "b", True), "tea_cache_start": (72, "i", 5), "tea_cache_end": (73, "i", -1),
    "tea_cache_threshold": (74, "f", 0.06), "tea_cache": (75, "b", False), "tea_cache_max_skip_steps": (78, "i", 3),
    "cfg_zero_star": (82, "b", False), "cfg_zero_init_steps": (83, "i", 0),
}


def build_config(
    *, width: int, height: int, model: str, refiner: str = "", refiner_start: float = 0.1,
    steps: int = 30, cfg: float = 3.5, shift: float = 5.0, frames: int = 1,
    seed: Optional[int] = None, sampler: int = 17, seed_mode: int = 2,
    strength: float = 1.0, loras: Iterable[tuple] = (), clip_skip: int = 1,
    adv: Optional[dict] = None,
) -> bytes:
    """Serialize GenerationConfiguration. width/height must be multiples of 64.
    `adv` holds optional advanced fields from ADV_FIELDS; unknown keys are ignored."""
    assert width % 64 == 0 and height % 64 == 0, "width/height must be multiples of 64"
    adv = {k: v for k, v in (adv or {}).items() if k in ADV_FIELDS and v is not None}
    b = flatbuffers.Builder(1024)
    model_o = b.CreateString(model)
    refiner_o = b.CreateString(refiner) if refiner else None
    adv_strings = {k: b.CreateString(str(v)) for k, v in adv.items() if ADV_FIELDS[k][1] == "s" and str(v)}

    lora_offsets = []
    for f, w, m in loras:
        fo = b.CreateString(f)
        b.StartObject(3)
        b.PrependUOffsetTRelativeSlot(0, fo, 0)
        b.PrependFloat32Slot(1, float(w), 0.6)
        b.PrependInt8Slot(2, int(m), 0)
        lora_offsets.append(b.EndObject())
    loras_o = None
    if lora_offsets:
        b.StartVector(4, len(lora_offsets), 4)
        for o in reversed(lora_offsets):
            b.PrependUOffsetTRelative(o)
        loras_o = b.EndVector()

    seed = seed if seed is not None else random.randint(1, 2**32 - 1)
    b.StartObject(92)
    b.PrependUint16Slot(1, width // 64, 0)          # start_width
    b.PrependUint16Slot(2, height // 64, 0)         # start_height
    b.PrependUint32Slot(3, seed, 0)                 # seed
    b.PrependUint32Slot(4, steps, 0)                # steps
    b.PrependFloat32Slot(5, float(cfg), 0)          # guidance_scale
    b.PrependFloat32Slot(6, float(strength), 0)     # strength
    b.PrependUOffsetTRelativeSlot(7, model_o, 0)    # model
    b.PrependInt8Slot(8, sampler, 0)                # sampler
    b.PrependUint32Slot(9, 1, 1)                    # batch_count
    b.PrependUint32Slot(10, 1, 1)                   # batch_size
    b.PrependInt8Slot(17, seed_mode, 0)             # seed_mode
    b.PrependUint32Slot(18, int(clip_skip), 1)      # clip_skip
    if loras_o is not None:
        b.PrependUOffsetTRelativeSlot(20, loras_o, 0)  # loras
    b.PrependFloat32Slot(21, 1.5, 0)                # mask_blur
    if refiner_o is not None:
        b.PrependUOffsetTRelativeSlot(28, refiner_o, 0)       # refiner_model
        b.PrependFloat32Slot(38, float(refiner_start), 0.7)   # refiner_start
    b.PrependUint32Slot(46, frames, 14)             # num_frames
    b.PrependInt32Slot(47, 0, 0)                    # mask_blur_outset
    b.PrependFloat32Slot(49, float(shift), 1.0)     # shift
    b.PrependBoolSlot(58, True, True)               # preserve_original_after_inpaint
    for k, v in adv.items():
        slot, kind, default = ADV_FIELDS[k]
        if kind == "s":
            if k in adv_strings:
                b.PrependUOffsetTRelativeSlot(slot, adv_strings[k], 0)
        elif kind == "f":
            b.PrependFloat32Slot(slot, float(v), default)
        elif kind == "u":
            b.PrependUint32Slot(slot, int(v), default)
        elif kind == "i":
            b.PrependInt32Slot(slot, int(v), default)
        elif kind == "b":
            b.PrependBoolSlot(slot, bool(v), default)
        elif kind == "h":
            b.PrependUint16Slot(slot, int(v), default)
        elif kind == "w":
            b.PrependUint16Slot(slot, int(v) // 64, default)
        elif kind == "B":
            b.PrependUint8Slot(slot, int(v), default)
    if "upscaler_scale_factor" not in adv:
        b.PrependUint8Slot(63, 0, 0)                # upscaler_scale_factor
    root = b.EndObject()
    b.Finish(root)
    return bytes(b.Output())


# ---------------------------------------------------------------- tensors

def encode_image(img: Image.Image, width: int, height: int) -> bytes:
    img = img.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
    arr = np.asarray(img, dtype=np.float32) * 2.0 / 255.0 - 1.0
    hdr = struct.pack("<17I", 0, CCV_CPU, NHWC, CCV_16F, 0, 1, height, width, 3, 0, 0, 0, 0, 0, 0, 0, 0)
    return hdr + arr.astype("<f2").tobytes()


def decode_tensor(buf: bytes) -> Image.Image:
    ident, = struct.unpack_from("<I", buf, 0)
    dims = struct.unpack_from("<12I", buf, 20)
    h, w, c = dims[1], dims[2], dims[3]
    n = h * w * c
    if ident == 0:
        a = np.frombuffer(buf, dtype="<f2", count=n, offset=HDR)
    elif ident == FPZIP_ID:
        import fpzip
        a = np.asarray(fpzip.decompress(buf[HDR:], order="C"), dtype=np.float16).reshape(-1)[:n]
    else:
        raise ValueError(f"unsupported tensor identifier {ident:#x}")
    px = np.clip(np.round((a.astype(np.float32) + 1.0) * 127.5), 0, 255).astype(np.uint8)
    return Image.fromarray(px.reshape(h, w, c)[..., :3])


# ---------------------------------------------------------------- client

def _cert_names(pem: bytes) -> list[str]:
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(pem)
        names: list[str] = []
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            names += san.value.get_values_for_type(x509.DNSName)
        except Exception:
            pass
        for attr in cert.subject:
            names.append(str(attr.value))
        return names
    except Exception:
        return []


class DrawThingsClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 7859, tls: bool = True, shared_secret: str = ""):
        self.host, self.port, self.tls, self.secret = host, port, tls, shared_secret
        self._channel: Optional[grpc.Channel] = None
        self._lock = threading.Lock()

    def _open(self) -> grpc.Channel:
        opts = [("grpc.max_receive_message_length", 1 << 30), ("grpc.max_send_message_length", 1 << 30)]
        target = f"{self.host}:{self.port}"
        if not self.tls:
            return grpc.insecure_channel(target, options=opts)
        pem = ssl.get_server_certificate((self.host, self.port)).encode()
        names = _cert_names(pem)
        opts.append(("grpc.ssl_target_name_override", names[0] if names else "localhost"))
        return grpc.secure_channel(target, grpc.ssl_channel_credentials(root_certificates=pem), options=opts)

    @property
    def stub(self) -> pbg.ImageGenerationServiceStub:
        with self._lock:
            if self._channel is None:
                self._channel = self._open()
            return pbg.ImageGenerationServiceStub(self._channel)

    def close(self):
        with self._lock:
            if self._channel:
                self._channel.close()
                self._channel = None

    def echo(self) -> dict:
        req = pb.EchoRequest(name="nandi")
        if self.secret:
            req.sharedSecret = self.secret
        r = self.stub.Echo(req, timeout=15)
        return {"message": r.message, "files": list(r.files), "shared_secret_missing": r.sharedSecretMissing}

    def generate(
        self, *, prompt: str, negative: str, config: bytes, image: Optional[bytes] = None,
        on_progress: Optional[Callable[[str, int], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> list[Image.Image]:
        """Run one generation; returns decoded frames in order."""
        req = pb.ImageGenerationRequest(
            prompt=prompt, negativePrompt=negative, configuration=config, scaleFactor=1,
            user="nandi", device=pb.LAPTOP, chunked=True,
        )
        if image is not None:
            req.image = image
        if self.secret:
            req.sharedSecret = self.secret
        call = self.stub.GenerateImage(req)
        raw_frames: list[bytes] = []
        pending = b""
        finished = threading.Event()

        def _watch():   # abort the RPC as soon as cancel is requested, not only when the next message arrives
            while not finished.is_set():
                if cancel_event is not None and cancel_event.wait(0.5):
                    call.cancel()
                    return
        if cancel_event is not None:
            threading.Thread(target=_watch, daemon=True).start()
        try:
            for r in call:
                if cancel_event is not None and cancel_event.is_set():
                    call.cancel()
                    raise GenerationCancelled()
                if r.HasField("currentSignpost") and on_progress:
                    which = r.currentSignpost.WhichOneof("signpost")
                    step = r.currentSignpost.sampling.step if which == "sampling" else (
                        r.currentSignpost.secondPassSampling.step if which == "secondPassSampling" else 0)
                    on_progress(which or "", step)
                for g in r.generatedImages:
                    if r.chunkState == pb.MORE_CHUNKS:
                        pending += g
                    else:
                        raw_frames.append(pending + g)
                        pending = b""
        except grpc.RpcError as e:
            if cancel_event is not None and cancel_event.is_set():
                raise GenerationCancelled() from e
            raise RuntimeError(f"Draw Things gRPC error: {e.code().name}: {e.details()}") from e
        finally:
            finished.set()
        if cancel_event is not None and cancel_event.is_set():
            raise GenerationCancelled()
        if not raw_frames:
            raise RuntimeError("Draw Things returned no images (generation failed or was cancelled in the app)")
        return [decode_tensor(f) for f in raw_frames]
