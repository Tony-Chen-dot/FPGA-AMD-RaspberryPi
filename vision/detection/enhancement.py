from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np

@dataclass(frozen=True)
class EnhancementConfig:
    clahe_clip_limit: float = 2.6
    clahe_tile_grid_size: int = 8
    contrast_gain: float = 1.18
    brightness_beta: float = -6.0
    detail_gain: float = 0.12
    sharpen_sigma: float = 1.1
    sharpen_amount: float = 0.82
    median_denoise_kernel: int = 3
    gaussian_denoise_sigma: float = 0.0
    bilateral_denoise_diameter: int = 5
    bilateral_denoise_sigma_color: float = 28.0
    bilateral_denoise_sigma_space: float = 28.0


class FrameEnhancer:
    def __init__(self, config: EnhancementConfig) -> None:
        grid = max(2, int(config.clahe_tile_grid_size))
        self.config = config
        self._clahe = cv2.createCLAHE(
            clipLimit=max(1.0, float(config.clahe_clip_limit)),
            tileGridSize=(grid, grid),
        )

    def enhance(self, frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        prepared = frame

        median_kernel = int(self.config.median_denoise_kernel)
        if median_kernel >= 3:
            if median_kernel % 2 == 0:
                median_kernel += 1
            prepared = cv2.medianBlur(prepared, median_kernel)

        bilateral_diameter = int(self.config.bilateral_denoise_diameter)
        if bilateral_diameter > 0:
            prepared = cv2.bilateralFilter(
                prepared,
                bilateral_diameter,
                float(self.config.bilateral_denoise_sigma_color),
                float(self.config.bilateral_denoise_sigma_space),
            )

        gaussian_sigma = max(0.0, float(self.config.gaussian_denoise_sigma))
        if gaussian_sigma > 0:
            prepared = cv2.GaussianBlur(prepared, (0, 0), sigmaX=gaussian_sigma, sigmaY=gaussian_sigma)

        # The production camera is monochrome. Keep it single-channel through
        # enhancement; only the legacy colour-camera fallback uses LAB.
        if prepared.ndim == 2:
            enhanced_gray = self._clahe.apply(prepared)

            detail_gain = max(0.0, float(self.config.detail_gain))
            if detail_gain > 0:
                local_blur = cv2.GaussianBlur(enhanced_gray, (0, 0), sigmaX=1.2, sigmaY=1.2)
                enhanced_gray = cv2.addWeighted(
                    enhanced_gray,
                    1.0 + detail_gain,
                    local_blur,
                    -detail_gain,
                    0,
                )

            contrast_gain = max(1.0, float(self.config.contrast_gain))
            brightness_beta = float(self.config.brightness_beta)
            if contrast_gain > 1.0 or brightness_beta != 0:
                enhanced_gray = cv2.convertScaleAbs(
                    enhanced_gray,
                    alpha=contrast_gain,
                    beta=brightness_beta,
                )

            sharpen_amount = max(0.0, float(self.config.sharpen_amount))
            if sharpen_amount > 0:
                sharpen_sigma = max(0.1, float(self.config.sharpen_sigma))
                softened = cv2.GaussianBlur(
                    enhanced_gray,
                    (0, 0),
                    sigmaX=sharpen_sigma,
                    sigmaY=sharpen_sigma,
                )
                enhanced_gray = cv2.addWeighted(
                    enhanced_gray,
                    1.0 + sharpen_amount,
                    softened,
                    -sharpen_amount,
                    0,
                )
            return enhanced_gray, enhanced_gray

        lab = cv2.cvtColor(prepared, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        l_channel = self._clahe.apply(l_channel)

        detail_gain = max(0.0, float(self.config.detail_gain))
        if detail_gain > 0:
            local_blur = cv2.GaussianBlur(l_channel, (0, 0), sigmaX=1.2, sigmaY=1.2)
            l_channel = cv2.addWeighted(l_channel, 1.0 + detail_gain, local_blur, -detail_gain, 0)

        contrast_gain = max(1.0, float(self.config.contrast_gain))
        brightness_beta = float(self.config.brightness_beta)
        if contrast_gain > 1.0 or brightness_beta != 0:
            l_channel = cv2.convertScaleAbs(l_channel, alpha=contrast_gain, beta=brightness_beta)

        enhanced = cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2BGR)
        sharpen_amount = max(0.0, float(self.config.sharpen_amount))
        if sharpen_amount > 0:
            sharpen_sigma = max(0.1, float(self.config.sharpen_sigma))
            softened = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=sharpen_sigma, sigmaY=sharpen_sigma)
            enhanced = cv2.addWeighted(enhanced, 1.0 + sharpen_amount, softened, -sharpen_amount, 0)

        enhanced_gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
        return enhanced, enhanced_gray

