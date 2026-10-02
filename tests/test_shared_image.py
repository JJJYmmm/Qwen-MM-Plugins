"""shared.image.smart_resize must keep the resized frame inside the token budget.

``max_pixels`` is the budget preset's token count times TOKEN_SIZE² (see ``budget_to_pixels``), so a
result above it sends the model more visual tokens than the preset allows. The docstring promises
``[min_pixels, max_pixels]``; the qwen-vl-utils reference floors to the patch grid when over the cap
so the bound always holds.
"""

import random

import pytest

from shared.env import IMAGE_BUDGET_TOKENS, IMAGE_MIN_PIXELS, TOKEN_SIZE, VIDEO_BUDGET_TOKENS, VIDEO_MIN_PIXELS
from shared.image import budget_to_pixels, smart_resize


@pytest.mark.parametrize(
    "height,width,budget",
    [
        (1080, 1920, "normal"),  # a 1080p frame: 768x1376 = 1032 tokens on a 1024-token budget
        (1920, 1080, "normal"),
        (3024, 4032, "large"),  # a 12 MP phone photo
    ],
)
def test_smart_resize_stays_within_image_budget(height, width, budget):
    max_pixels = budget_to_pixels(budget, IMAGE_BUDGET_TOKENS)
    h, w = smart_resize(height, width, IMAGE_MIN_PIXELS, max_pixels)
    assert h % TOKEN_SIZE == 0 and w % TOKEN_SIZE == 0
    assert h * w <= max_pixels, f"{h}x{w} = {h * w // TOKEN_SIZE**2} tokens > {max_pixels // TOKEN_SIZE**2}"


@pytest.mark.parametrize(
    "tokens_map,min_pixels",
    [(IMAGE_BUDGET_TOKENS, IMAGE_MIN_PIXELS), (VIDEO_BUDGET_TOKENS, VIDEO_MIN_PIXELS)],
    ids=["image", "video"],
)
def test_smart_resize_downscale_never_exceeds_max_pixels(tokens_map, min_pixels):
    # Every source larger than the budget must come out at or under it, for every preset.
    rng = random.Random(0)
    over = []
    for budget in tokens_map:
        max_pixels = budget_to_pixels(budget, tokens_map)
        for _ in range(300):
            height, width = rng.randint(64, 4096), rng.randint(64, 4096)
            if height * width <= max_pixels:
                continue
            h, w = smart_resize(height, width, min_pixels, max_pixels)
            if h * w > max_pixels:
                over.append((budget, height, width, h, w))
    assert not over, f"{len(over)} sizes exceed max_pixels, e.g. {over[:3]}"


@pytest.mark.parametrize(
    "height,width,tokens_map,min_pixels",
    [
        (200, 300, IMAGE_BUDGET_TOKENS, IMAGE_MIN_PIXELS),  # 416x640 = 260 tokens on a 256-token budget
        (144, 256, VIDEO_BUDGET_TOKENS, VIDEO_MIN_PIXELS),  # 224x384 = 84 tokens on an 80-token budget
        (180, 320, VIDEO_BUDGET_TOKENS, VIDEO_MIN_PIXELS),
    ],
)
def test_smart_resize_upscale_on_small_preset_stays_within_budget(height, width, tokens_map, min_pixels):
    # The small presets set min_pixels == max_pixels, which the 32-px grid usually cannot hit exactly;
    # growing a small source toward min_pixels must still not go over the budget.
    max_pixels = budget_to_pixels("small", tokens_map)
    assert min_pixels == max_pixels
    h, w = smart_resize(height, width, min_pixels, max_pixels)
    assert h % TOKEN_SIZE == 0 and w % TOKEN_SIZE == 0
    assert h * w <= max_pixels, f"{h}x{w} = {h * w // TOKEN_SIZE**2} tokens > {max_pixels // TOKEN_SIZE**2}"
