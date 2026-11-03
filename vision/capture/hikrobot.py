from __future__ import annotations

import importlib
import os
import platform
import sys
from ctypes import POINTER, byref, c_ubyte, cast, memset, sizeof
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class HikrobotDeviceInfo:
    index: int
    layer_type: int
    model_name: str
    serial_number: str


class HikrobotCameraError(RuntimeError):
    pass


def _decode_char_array(values) -> str:
    data = bytes(int(item) & 0xFF for item in values if item != 0)
    return data.decode("utf-8", errors="ignore").strip()


def _candidate_mvimport_paths(sdk_root: Path) -> list[Path]:
    machine = platform.machine()
    return [
        sdk_root / "Samples" / machine / "Python" / "MvImport",
        sdk_root / "Samples" / "aarch64" / "Python" / "MvImport",
        sdk_root / "Samples" / "arm64" / "Python" / "MvImport",
        sdk_root / "Samples" / "Python" / "MvImport",
    ]


def _prepare_sdk_environment(sdk_root: Path) -> Path:
    sdk_root = sdk_root.resolve()
    if not sdk_root.exists():
        raise HikrobotCameraError(f"未找到海康 MVS SDK 目录: {sdk_root}")

    lib_root = sdk_root / "lib"
    if not lib_root.exists():
        raise HikrobotCameraError(f"海康 MVS SDK 缺少 lib 目录: {lib_root}")

    os.environ["MVCAM_SDK_PATH"] = str(sdk_root)
    os.environ["MVCAM_COMMON_RUNENV"] = str(lib_root)
    os.environ["MVCAM_SOFTWARE_LIBENV"] = str(lib_root)
    os.environ["MVCAM_GENICAM_CLPROTOCOL"] = str(lib_root / "CLProtocol")
    os.environ.setdefault("ALLUSERSPROFILE", str(sdk_root / "MVFG"))

    arch_dirs = [lib_root / "aarch64", lib_root / "64", lib_root / "armhf", lib_root / "arm-none", lib_root / "32"]
    existing_ld = [entry for entry in os.environ.get("LD_LIBRARY_PATH", "").split(":") if entry]
    new_ld = [str(path) for path in arch_dirs if path.exists()]
    merged_ld: list[str] = []
    for path in new_ld + existing_ld:
        if path and path not in merged_ld:
            merged_ld.append(path)
    os.environ["LD_LIBRARY_PATH"] = ":".join(merged_ld)

    for candidate in _candidate_mvimport_paths(sdk_root):
        if candidate.exists():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return candidate

    raise HikrobotCameraError(f"未找到海康 Python 接口目录，已检查: {', '.join(str(path) for path in _candidate_mvimport_paths(sdk_root))}")


def _load_mvs_module(sdk_root: Path):
    _prepare_sdk_environment(sdk_root)
    return importlib.import_module("MvCameraControl_class")


def _describe_device(module, index: int, device_list) -> HikrobotDeviceInfo:
    dev_info = cast(device_list.pDeviceInfo[index], POINTER(module.MV_CC_DEVICE_INFO)).contents
    layer_type = int(dev_info.nTLayerType)
    model_name = ""
    serial_number = ""

    if layer_type == module.MV_USB_DEVICE:
        model_name = _decode_char_array(dev_info.SpecialInfo.stUsb3VInfo.chModelName)
        serial_number = _decode_char_array(dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber)
    elif layer_type in (module.MV_GIGE_DEVICE, getattr(module, "MV_GENTL_GIGE_DEVICE", -1)):
        model_name = _decode_char_array(dev_info.SpecialInfo.stGigEInfo.chModelName)
        serial_number = _decode_char_array(dev_info.SpecialInfo.stGigEInfo.chSerialNumber)
    elif layer_type == getattr(module, "MV_GENTL_CAMERALINK_DEVICE", -1):
        model_name = _decode_char_array(dev_info.SpecialInfo.stCMLInfo.chModelName)
        serial_number = _decode_char_array(dev_info.SpecialInfo.stCMLInfo.chSerialNumber)
    elif layer_type == getattr(module, "MV_GENTL_CXP_DEVICE", -1):
        model_name = _decode_char_array(dev_info.SpecialInfo.stCXPInfo.chModelName)
        serial_number = _decode_char_array(dev_info.SpecialInfo.stCXPInfo.chSerialNumber)
    elif layer_type == getattr(module, "MV_GENTL_XOF_DEVICE", -1):
        model_name = _decode_char_array(dev_info.SpecialInfo.stXoFInfo.chModelName)
        serial_number = _decode_char_array(dev_info.SpecialInfo.stXoFInfo.chSerialNumber)

    return HikrobotDeviceInfo(
        index=index,
        layer_type=layer_type,
        model_name=model_name or "Unknown",
        serial_number=serial_number or "",
    )


def enumerate_hikrobot_devices(sdk_root: str | os.PathLike[str] = "/opt/MVS") -> list[HikrobotDeviceInfo]:
    module = _load_mvs_module(Path(sdk_root))
    module.MvCamera.MV_CC_Initialize()
    try:
        device_list = module.MV_CC_DEVICE_INFO_LIST()
        tlayer_type = (
            module.MV_GIGE_DEVICE
            | module.MV_USB_DEVICE
            | getattr(module, "MV_GENTL_GIGE_DEVICE", 0)
            | getattr(module, "MV_GENTL_CAMERALINK_DEVICE", 0)
            | getattr(module, "MV_GENTL_CXP_DEVICE", 0)
            | getattr(module, "MV_GENTL_XOF_DEVICE", 0)
        )
        ret = module.MvCamera.MV_CC_EnumDevices(tlayer_type, device_list)
        if ret != 0:
            raise HikrobotCameraError(f"枚举海康设备失败: 0x{ret:x}")
        return [_describe_device(module, index, device_list) for index in range(int(device_list.nDeviceNum))]
    finally:
        module.MvCamera.MV_CC_Finalize()


def _is_hb_pixel_format(module, pixel_type: int) -> bool:
    hb_types = {
        module.PixelType_Gvsp_HB_Mono8,
        module.PixelType_Gvsp_HB_Mono10,
        module.PixelType_Gvsp_HB_Mono10_Packed,
        module.PixelType_Gvsp_HB_Mono12,
        module.PixelType_Gvsp_HB_Mono12_Packed,
        module.PixelType_Gvsp_HB_Mono16,
        module.PixelType_Gvsp_HB_RGB8_Packed,
        module.PixelType_Gvsp_HB_BGR8_Packed,
        module.PixelType_Gvsp_HB_RGBA8_Packed,
        module.PixelType_Gvsp_HB_BGRA8_Packed,
        module.PixelType_Gvsp_HB_RGB16_Packed,
        module.PixelType_Gvsp_HB_BGR16_Packed,
        module.PixelType_Gvsp_HB_RGBA16_Packed,
        module.PixelType_Gvsp_HB_BGRA16_Packed,
        module.PixelType_Gvsp_HB_YUV422_Packed,
        module.PixelType_Gvsp_HB_YUV422_YUYV_Packed,
        module.PixelType_Gvsp_HB_BayerGR8,
        module.PixelType_Gvsp_HB_BayerRG8,
        module.PixelType_Gvsp_HB_BayerGB8,
        module.PixelType_Gvsp_HB_BayerBG8,
        module.PixelType_Gvsp_HB_BayerRBGG8,
        module.PixelType_Gvsp_HB_BayerGB10,
        module.PixelType_Gvsp_HB_BayerGB10_Packed,
        module.PixelType_Gvsp_HB_BayerBG10,
        module.PixelType_Gvsp_HB_BayerBG10_Packed,
        module.PixelType_Gvsp_HB_BayerRG10,
        module.PixelType_Gvsp_HB_BayerRG10_Packed,
        module.PixelType_Gvsp_HB_BayerGR10,
        module.PixelType_Gvsp_HB_BayerGR10_Packed,
        module.PixelType_Gvsp_HB_BayerGB12,
        module.PixelType_Gvsp_HB_BayerGB12_Packed,
        module.PixelType_Gvsp_HB_BayerBG12,
        module.PixelType_Gvsp_HB_BayerBG12_Packed,
        module.PixelType_Gvsp_HB_BayerRG12,
        module.PixelType_Gvsp_HB_BayerRG12_Packed,
        module.PixelType_Gvsp_HB_BayerGR12,
        module.PixelType_Gvsp_HB_BayerGR12_Packed,
    }
    return pixel_type in hb_types


def _is_mono_pixel_format(module, pixel_type: int) -> bool:
    mono_types = {
        module.PixelType_Gvsp_Mono8,
        module.PixelType_Gvsp_Mono10,
        module.PixelType_Gvsp_Mono10_Packed,
        module.PixelType_Gvsp_Mono12,
        module.PixelType_Gvsp_Mono12_Packed,
        module.PixelType_Gvsp_Mono14,
        module.PixelType_Gvsp_Mono16,
    }
    return pixel_type in mono_types


class HikrobotCameraCapture:
    def __init__(
        self,
        sdk_root: str | os.PathLike[str] = "/opt/MVS",
        camera_index: int = 0,
        serial_number: str | None = None,
        width: int = 1280,
        height: int = 720,
        fps: float = 18.0,
        frame_timeout_ms: int = 200,
    ) -> None:
        self.sdk_root = Path(sdk_root)
        self.camera_index = max(0, int(camera_index))
        self.serial_number = (serial_number or "").strip()
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.fps = max(1.0, float(fps))
        self.frame_timeout_ms = max(10, int(frame_timeout_ms))
        self.backend_name = "HIKROBOT-MVS"
        self.device_description = "unknown"
        self._module = _load_mvs_module(self.sdk_root)
        self._camera = self._module.MvCamera()
        self._sdk_initialized = False
        self._opened = False
        self._selected_device_index = -1
        self._selected_device = None
        self.capture_width = self.width
        self.capture_height = self.height

        self._module.MvCamera.MV_CC_Initialize()
        self._sdk_initialized = True
        try:
            self._open()
        except Exception:
            self.release()
            raise

    def _open(self) -> None:
        device_list = self._module.MV_CC_DEVICE_INFO_LIST()
        tlayer_type = (
            self._module.MV_GIGE_DEVICE
            | self._module.MV_USB_DEVICE
            | getattr(self._module, "MV_GENTL_GIGE_DEVICE", 0)
            | getattr(self._module, "MV_GENTL_CAMERALINK_DEVICE", 0)
            | getattr(self._module, "MV_GENTL_CXP_DEVICE", 0)
            | getattr(self._module, "MV_GENTL_XOF_DEVICE", 0)
        )
        ret = self._module.MvCamera.MV_CC_EnumDevices(tlayer_type, device_list)
        if ret != 0:
            raise HikrobotCameraError(f"枚举海康设备失败: 0x{ret:x}")
        if int(device_list.nDeviceNum) <= 0:
            raise HikrobotCameraError("未找到任何海康 MVS 相机")

        devices = [_describe_device(self._module, index, device_list) for index in range(int(device_list.nDeviceNum))]
        selected = None
        if self.serial_number:
            for item in devices:
                if item.serial_number == self.serial_number:
                    selected = item
                    break
            if selected is None:
                available = ", ".join(f"{item.index}:{item.model_name}/{item.serial_number}" for item in devices)
                raise HikrobotCameraError(f"未找到序列号为 {self.serial_number} 的海康相机。当前设备: {available}")
        else:
            if self.camera_index >= len(devices):
                available = ", ".join(f"{item.index}:{item.model_name}/{item.serial_number}" for item in devices)
                raise HikrobotCameraError(f"海康相机索引 {self.camera_index} 超出范围。当前设备: {available}")
            selected = devices[self.camera_index]

        self._selected_device_index = selected.index
        self._selected_device = selected
        self.device_description = f"{selected.model_name} serial={selected.serial_number or '--'} index={selected.index}"

        st_device = cast(device_list.pDeviceInfo[selected.index], POINTER(self._module.MV_CC_DEVICE_INFO)).contents
        ret = self._camera.MV_CC_CreateHandle(st_device)
        if ret != 0:
            raise HikrobotCameraError(f"创建海康相机句柄失败: 0x{ret:x}")

        ret = self._camera.MV_CC_OpenDevice(self._module.MV_ACCESS_Exclusive, 0)
        if ret != 0:
            raise HikrobotCameraError(f"打开海康相机失败: 0x{ret:x}")

        if selected.layer_type in (self._module.MV_GIGE_DEVICE, getattr(self._module, "MV_GENTL_GIGE_DEVICE", -1)):
            packet_size = int(self._camera.MV_CC_GetOptimalPacketSize())
            if packet_size > 0:
                self._camera.MV_CC_SetIntValue("GevSCPSPacketSize", packet_size)

        self._try_set_enum_value("TriggerMode", self._module.MV_TRIGGER_MODE_OFF)
        self._try_set_enum_string("AcquisitionMode", "Continuous")
        # The installed camera is monochrome. Prefer Mono8 so the SDK does not
        # create an unnecessary RGB/BGR image for every frame. Older SDKs may
        # not expose a writable PixelFormat node, so keep the existing fallback.
        try:
            self._try_set_enum_string("PixelFormat", "Mono8")
        except Exception:
            pass
        self._configure_full_sensor_roi()
        self._try_set_bool_value("AcquisitionFrameRateEnable", True)
        self._try_set_float_value("AcquisitionFrameRate", self.fps)

        ret = self._camera.MV_CC_StartGrabbing()
        if ret != 0:
            raise HikrobotCameraError(f"海康相机开始取流失败: 0x{ret:x}")
        self._opened = True

    def isOpened(self) -> bool:
        return self._opened

    def _try_set_int_value(self, key: str, value: int) -> bool:
        return self._camera.MV_CC_SetIntValueEx(key, int(value)) == 0

    def _get_int_value(self, key: str) -> int | None:
        value_info_type = getattr(self._module, "MVCC_INTVALUE_EX", None)
        if value_info_type is None:
            return None
        value_info = value_info_type()
        memset(byref(value_info), 0, sizeof(value_info))
        try:
            ret = self._camera.MV_CC_GetIntValueEx(key, value_info)
        except Exception:
            return None
        if ret != 0:
            return None
        current = getattr(value_info, "nCurValue", None)
        return int(current) if current is not None else None

    def _configure_full_sensor_roi(self) -> None:
        """Use the complete sensor ROI, then normalize each frame to the old output size."""
        for key in ("OffsetX", "OffsetY"):
            try:
                self._try_set_int_value(key, 0)
            except Exception:
                pass

        width_max = self._get_int_value("WidthMax")
        height_max = self._get_int_value("HeightMax")
        if width_max is None:
            width_max = self._get_int_value("Width")
        if height_max is None:
            height_max = self._get_int_value("Height")
        if width_max and height_max:
            try:
                width_set = self._try_set_int_value("Width", width_max)
                height_set = self._try_set_int_value("Height", height_max)
                if width_set and height_set:
                    self.capture_width = self._get_int_value("Width") or width_max
                    self.capture_height = self._get_int_value("Height") or height_max
                    return
            except Exception:
                pass

        # Keep the previous behavior on SDKs that do not expose WidthMax/HeightMax.
        self._try_set_int_value("Width", self.width)
        self._try_set_int_value("Height", self.height)

    def _try_set_float_value(self, key: str, value: float) -> None:
        self._camera.MV_CC_SetFloatValue(key, float(value))

    def _try_set_bool_value(self, key: str, value: bool) -> None:
        self._camera.MV_CC_SetBoolValue(key, bool(value))

    def _try_set_enum_value(self, key: str, value: int) -> None:
        self._camera.MV_CC_SetEnumValue(key, int(value))

    def _try_set_enum_string(self, key: str, value: str) -> None:
        self._camera.MV_CC_SetEnumValueByString(key, value)

    def read(self):
        ok, frame = self.read_native()
        return (True, self._resize_to_output(frame)) if ok else (False, None)

    def read_with_preview(self):
        """Pair the unchanged detection input with the unpadded sensor frame."""
        ok, frame = self.read_native()
        if not ok:
            return False, None, None
        return True, self._resize_to_output(frame), frame

    def read_native(self):
        if not self._opened:
            return False, None

        st_out_frame = self._module.MV_FRAME_OUT()
        memset(byref(st_out_frame), 0, sizeof(st_out_frame))
        ret = self._camera.MV_CC_GetImageBuffer(st_out_frame, self.frame_timeout_ms)
        if ret != 0 or st_out_frame.pBufAddr is None:
            return False, None

        try:
            frame_info = st_out_frame.stFrameInfo
            src_pixel_type = int(frame_info.enPixelType)
            src_data = st_out_frame.pBufAddr
            src_len = int(frame_info.nFrameLen)

            if _is_hb_pixel_format(self._module, src_pixel_type):
                decode_param = self._module.MV_CC_HB_DECODE_PARAM()
                memset(byref(decode_param), 0, sizeof(decode_param))
                decode_buffer_len = int(frame_info.nWidth * frame_info.nHeight * 3)
                decode_buffer = (c_ubyte * decode_buffer_len)()
                decode_param.pSrcBuf = src_data
                decode_param.nSrcLen = src_len
                decode_param.pDstBuf = decode_buffer
                decode_param.nDstBufSize = decode_buffer_len
                ret = self._camera.MV_CC_HBDecode(decode_param)
                if ret != 0:
                    return False, None
                src_data = decode_param.pDstBuf
                src_len = int(decode_param.nDstBufLen)
                src_pixel_type = int(decode_param.enDstPixelType)

            convert_param = self._module.MV_CC_PIXEL_CONVERT_PARAM_EX()
            memset(byref(convert_param), 0, sizeof(convert_param))
            convert_param.nWidth = int(frame_info.nWidth)
            convert_param.nHeight = int(frame_info.nHeight)
            convert_param.pSrcData = src_data
            convert_param.nSrcDataLen = src_len
            convert_param.enSrcPixelType = src_pixel_type

            if _is_mono_pixel_format(self._module, src_pixel_type):
                dst_pixel_type = self._module.PixelType_Gvsp_Mono8
                channel_count = 1
            else:
                dst_pixel_type = self._module.PixelType_Gvsp_BGR8_Packed
                channel_count = 3

            dst_buffer_len = int(frame_info.nWidth * frame_info.nHeight * channel_count)
            dst_buffer = (c_ubyte * dst_buffer_len)()
            convert_param.enDstPixelType = dst_pixel_type
            convert_param.pDstBuffer = dst_buffer
            convert_param.nDstBufferSize = dst_buffer_len

            ret = self._camera.MV_CC_ConvertPixelTypeEx(convert_param)
            if ret != 0:
                return False, None

            if channel_count == 1:
                mono = np.frombuffer(dst_buffer, dtype=np.uint8, count=dst_buffer_len).reshape(
                    int(frame_info.nHeight),
                    int(frame_info.nWidth),
                ).copy()
                frame = mono
            else:
                frame = np.frombuffer(dst_buffer, dtype=np.uint8, count=dst_buffer_len).reshape(
                    int(frame_info.nHeight),
                    int(frame_info.nWidth),
                    3,
                ).copy()

            return True, frame
        finally:
            self._camera.MV_CC_FreeImageBuffer(st_out_frame)

    def _resize_to_output(self, frame):
        source_height, source_width = frame.shape[:2]
        if source_width == self.width and source_height == self.height:
            return frame

        scale = min(self.width / source_width, self.height / source_height)
        resized_width = max(1, int(round(source_width * scale)))
        resized_height = max(1, int(round(source_height * scale)))
        interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        resized = cv2.resize(frame, (resized_width, resized_height), interpolation=interpolation)
        if frame.ndim == 2:
            output = np.zeros((self.height, self.width), dtype=frame.dtype)
        else:
            output = np.zeros((self.height, self.width, frame.shape[2]), dtype=frame.dtype)
        offset_x = (self.width - resized_width) // 2
        offset_y = (self.height - resized_height) // 2
        output[offset_y : offset_y + resized_height, offset_x : offset_x + resized_width] = resized
        return output

    def release(self) -> None:
        if self._opened:
            self._camera.MV_CC_StopGrabbing()
            self._camera.MV_CC_CloseDevice()
            self._opened = False
        try:
            self._camera.MV_CC_DestroyHandle()
        except Exception:
            pass
        if self._sdk_initialized:
            self._module.MvCamera.MV_CC_Finalize()
            self._sdk_initialized = False
