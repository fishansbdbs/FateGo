import cv2
import numpy as np
import pytest

from fgo_guardian.models import Rect
from fgo_guardian.viewport_mapper import ViewportMapper


def synthetic_ldplayer(
    titlebar_bottom: int = 40,
    toolbar_left: int = 1825,
    chrome_level: int = 230,
) -> np.ndarray:
    image = np.full((1040, 1920, 3), 28, dtype=np.uint8)
    image[titlebar_bottom:1040, 55:toolbar_left] = (70, 45, 25)
    image[titlebar_bottom:1040, toolbar_left:1920] = (36, 36, 40)
    chrome = (chrome_level, chrome_level, chrome_level)
    cv2.line(image, (0, titlebar_bottom - 1), (1919, titlebar_bottom - 1), chrome, 2)
    cv2.line(image, (toolbar_left - 1, titlebar_bottom), (toolbar_left - 1, 1039), chrome, 2)
    return image


def test_locate_returns_landscape_16_by_9_viewport() -> None:
    mapping = ViewportMapper().locate(synthetic_ldplayer())
    assert abs(mapping.viewport.width / mapping.viewport.height - 16 / 9) < 0.01
    assert mapping.titlebar_bottom in range(35, 46)
    assert mapping.toolbar_left in range(1818, 1832)
    assert mapping.viewport.left >= 0
    assert mapping.viewport.right <= mapping.toolbar_left


def test_normalized_geometry_is_bounded_by_viewport() -> None:
    mapping = ViewportMapper().locate(synthetic_ldplayer())
    rect = mapping.normalized_rect((0.25, 0.25, 0.75, 0.75))
    assert mapping.viewport.left <= rect.left < rect.right <= mapping.viewport.right
    assert mapping.viewport.top <= rect.top < rect.bottom <= mapping.viewport.bottom
    assert mapping.normalized_target(rect) == pytest.approx(
        (0.25, 0.25, 0.75, 0.75),
        abs=1 / min(mapping.viewport.width, mapping.viewport.height),
    )


def test_locate_rejects_frame_too_small_for_fgo() -> None:
    tiny = np.zeros((200, 300, 3), dtype=np.uint8)
    try:
        ViewportMapper().locate(tiny)
    except ValueError as error:
        assert "too small" in str(error)
    else:
        raise AssertionError("tiny frame was accepted")


def test_locate_rejects_large_frame_without_credible_chrome_edges() -> None:
    uniform = np.zeros((1040, 1920, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="too weak"):
        ViewportMapper().locate(uniform)


def test_locate_validates_in_game_distractor_structure() -> None:
    image = synthetic_ldplayer(chrome_level=120)
    cv2.line(image, (0, 110), (1919, 110), (255, 255, 255), 2)
    mapping = ViewportMapper().locate(image)
    assert mapping.titlebar_bottom in range(35, 46)

    ambiguous = synthetic_ldplayer()
    ambiguous[114:1040] = np.clip(ambiguous[114:1040].astype(int) + 24, 0, 255).astype(np.uint8)
    cv2.line(ambiguous, (0, 110), (1919, 110), (230, 230, 230), 2)
    with pytest.raises(ValueError, match="ambiguous"):
        ViewportMapper().locate(ambiguous)


def test_locate_prefers_top_chrome_over_weaker_battle_hud_edges() -> None:
    mapper = ViewportMapper()
    baseline = mapper.locate(
        synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825)
    )
    image = synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825)
    edge = 95
    image[edge + 1:150, :1700] = np.clip(
        image[edge + 1:150, :1700].astype(int) + 70,
        0,
        255,
    ).astype(np.uint8)
    image[edge + 1:150, 1750:1810] = np.clip(
        image[edge + 1:150, 1750:1810].astype(int) + 70,
        0,
        255,
    ).astype(np.uint8)

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    distractor = edge - 2 + int(
        np.argmax(np.mean(gradient[edge - 2:edge + 3], axis=1))
    )
    trailing_width = max(
        1, round(baseline.toolbar_left * mapper.TRAILING_EDGE_SUPPORT_FRACTION)
    )
    full_support = float(
        np.mean(gradient[distractor] >= mapper.MIN_EDGE_STRENGTH)
    )
    trailing_support = float(
        np.mean(
            gradient[
                distractor,
                baseline.toolbar_left - trailing_width:baseline.toolbar_left,
            ]
            >= mapper.MIN_EDGE_STRENGTH
        )
    )
    assert full_support >= mapper.MIN_TITLEBAR_FULL_SUPPORT
    assert trailing_support >= mapper.MIN_TITLEBAR_BOUNDED_SUPPORT
    assert trailing_support < 0.80

    mapping = mapper.locate(image)

    assert mapping.signature == baseline.signature


def test_locate_accepts_shifted_but_unambiguous_chrome() -> None:
    mapping = ViewportMapper().locate(synthetic_ldplayer(titlebar_bottom=100, toolbar_left=1700))
    assert mapping.titlebar_bottom in range(95, 106)
    assert mapping.toolbar_left in range(1693, 1707)


def test_locate_accepts_partial_titlebar_edge_under_dim_tutorial_overlay() -> None:
    mapper = ViewportMapper()
    baseline = mapper.locate(synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825))
    image = synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825)

    # The Formation tutorial dimmer makes most of the first game rows look like
    # the LDPlayer titlebar.  This recreates the measured live edge support while
    # keeping the emulator's chrome geometry unchanged.
    for left, right in ((995, 1720), (1760, 1920)):
        image[37:140, left:right] = (28, 28, 28)
    cv2.line(image, (1824, 140), (1824, 1039), (230, 230, 230), 2)

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    edge = 37
    trailing_width = max(
        1, round(baseline.toolbar_left * mapper.TRAILING_EDGE_SUPPORT_FRACTION)
    )
    full_support = float(np.mean(gradient[edge] >= mapper.MIN_EDGE_STRENGTH))
    trailing_support = float(
        np.mean(
            gradient[
                edge,
                baseline.toolbar_left - trailing_width:baseline.toolbar_left,
            ]
            >= mapper.MIN_EDGE_STRENGTH
        )
    )
    assert full_support == pytest.approx(0.54, abs=0.01)
    assert trailing_support == pytest.approx(0.30, abs=0.02)
    assert mapper._sustained_contrast(image, edge, 0) >= mapper.MIN_SUSTAINED_CONTRAST

    mapping = mapper.locate(image)

    assert mapping.signature == baseline.signature


def test_locate_accepts_sparse_titlebar_edge_with_full_trailing_support() -> None:
    mapper = ViewportMapper()
    baseline = mapper.locate(synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825))
    image = synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825)

    # The dim Servant-selection tutorial preserves the titlebar boundary in the
    # LDPlayer-side anchor band but obscures it across most of the game content.
    for left, right in ((735, 1734), (1825, 1920)):
        image[37:140, left:right] = (28, 28, 28)
    cv2.line(image, (1824, 140), (1824, 1039), (230, 230, 230), 2)

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    edge = 37
    trailing_width = max(
        1, round(baseline.toolbar_left * mapper.TRAILING_EDGE_SUPPORT_FRACTION)
    )
    full_support = float(np.mean(gradient[edge] >= mapper.MIN_EDGE_STRENGTH))
    trailing_support = float(
        np.mean(
            gradient[
                edge,
                baseline.toolbar_left - trailing_width:baseline.toolbar_left,
            ]
            >= mapper.MIN_EDGE_STRENGTH
        )
    )
    assert full_support == pytest.approx(0.43, abs=0.01)
    assert trailing_support == pytest.approx(0.99, abs=0.02)
    assert mapper._sustained_contrast(image, edge, 0) >= mapper.MIN_SUSTAINED_CONTRAST

    mapping = mapper.locate(image)

    assert mapping.signature == baseline.signature


def test_locate_ignores_full_height_outer_window_border_after_toolbar() -> None:
    mapper = ViewportMapper()
    baseline_image = synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825)
    baseline = mapper.locate(baseline_image)
    image = baseline_image.copy()
    outer_border_left = round(image.shape[1] * 0.997)
    image[:, outer_border_left:] = (245, 245, 245)

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    profile = np.mean(gradient, axis=0)
    candidate = outer_border_left - 1
    band_top = round(image.shape[0] * mapper.TOOLBAR_SUPPORT_BAND[0])
    band_bottom = round(image.shape[0] * mapper.TOOLBAR_SUPPORT_BAND[1])
    assert float(profile[candidate]) >= mapper.MIN_EDGE_STRENGTH
    assert mapper._sustained_contrast(image, candidate, 1) >= mapper.MIN_SUSTAINED_CONTRAST
    assert float(np.mean(gradient[:, candidate] >= mapper.MIN_EDGE_STRENGTH)) >= mapper.MIN_EDGE_SUPPORT
    assert float(
        np.mean(gradient[band_top:band_bottom, candidate] >= mapper.MIN_EDGE_STRENGTH)
    ) >= mapper.MIN_TOOLBAR_BOUNDED_SUPPORT

    mapping = mapper.locate(image)

    assert mapping.signature == baseline.signature


def test_locate_ignores_wide_result_panel_that_ends_before_toolbar() -> None:
    mapper = ViewportMapper()
    baseline = mapper.locate(synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825))
    image = synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825)
    image[245:840, 120:1740] = (8, 8, 8)
    cv2.line(image, (120, 244), (1739, 244), (235, 235, 235), 2)

    mapping = mapper.locate(image)

    assert mapping.signature == baseline.signature


def test_locate_rejects_trailing_band_only_edge_as_titlebar() -> None:
    mapper = ViewportMapper()
    baseline = mapper.locate(synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825))
    trailing_width = max(
        1, round(baseline.toolbar_left * mapper.TRAILING_EDGE_SUPPORT_FRACTION)
    )
    band_left = baseline.toolbar_left - trailing_width
    image = synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825)
    image[111:220, band_left:baseline.toolbar_left] = (245, 245, 245)
    cv2.line(
        image,
        (band_left, 110),
        (baseline.toolbar_left - 1, 110),
        (8, 8, 8),
        2,
    )

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    distractor = 100 + int(np.argmax(np.mean(gradient[100:120], axis=1)))
    support = gradient[distractor] >= mapper.MIN_EDGE_STRENGTH
    assert float(np.mean(gradient[distractor])) >= mapper.MIN_EDGE_STRENGTH
    assert mapper._sustained_contrast(image, distractor, 0) >= mapper.MIN_SUSTAINED_CONTRAST
    assert float(np.mean(support[band_left:baseline.toolbar_left])) >= mapper.MIN_EDGE_SUPPORT
    assert float(np.mean(support)) < mapper.MIN_EDGE_SUPPORT

    mapping = mapper.locate(image)

    assert mapping.signature == baseline.signature


def test_locate_ignores_tall_items_panel_that_ends_above_toolbar_support_band() -> None:
    mapper = ViewportMapper()
    baseline = mapper.locate(synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825))
    image = synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825)
    image[48:874, 120:1690] = (8, 8, 8)
    cv2.line(image, (120, 47), (1689, 47), (235, 235, 235), 2)
    cv2.line(image, (120, 874), (1689, 874), (235, 235, 235), 2)
    cv2.line(image, (1689, 47), (1689, 874), (235, 235, 235), 2)

    mapping = mapper.locate(image)

    assert mapping.signature == baseline.signature


def test_locate_rejects_lower_interior_band_only_edge_as_toolbar() -> None:
    mapper = ViewportMapper()
    baseline = mapper.locate(synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825))
    image = synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825)
    band_top = round(image.shape[0] * 0.85)
    band_bottom = round(image.shape[0] * 0.90)
    edge = 1600
    image[band_top:band_bottom, edge + 1:1700] = (245, 245, 245)
    cv2.line(image, (edge, band_top), (edge, band_bottom - 1), (8, 8, 8), 2)

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    distractor = edge - 10 + int(
        np.argmax(np.mean(gradient[:, edge - 10:edge + 10], axis=0))
    )
    support = gradient[:, distractor] >= mapper.MIN_EDGE_STRENGTH
    assert float(np.mean(gradient[:, distractor])) >= mapper.MIN_EDGE_STRENGTH
    assert mapper._sustained_contrast(image, distractor, 1) >= mapper.MIN_SUSTAINED_CONTRAST
    assert float(np.mean(support[band_top:band_bottom])) >= mapper.MIN_EDGE_SUPPORT
    assert float(np.mean(support)) < mapper.MIN_EDGE_SUPPORT

    mapping = mapper.locate(image)

    assert mapping.signature == baseline.signature


def test_locate_uses_rightmost_credible_toolbar_edge_past_tall_scroll_rails() -> None:
    mapper = ViewportMapper()
    image = synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825)
    baseline = mapper.locate(image)

    # Support Select renders tall scroll rails immediately inside the Android
    # viewport.  They can have enough full-height and lower-band support to be
    # individually credible, but the LDPlayer toolbar boundary remains the
    # rightmost credible vertical chrome edge.
    image[40:, 1766:1795] = (235, 235, 235)

    mapping = mapper.locate(image)

    assert mapping.signature == baseline.signature


def test_locate_ignores_qualified_shoulder_before_dominant_toolbar_plateau() -> None:
    edge = 1824

    def toolbar_with_shoulder(shoulder: bool) -> np.ndarray:
        image = synthetic_ldplayer(titlebar_bottom=40, toolbar_left=1825)
        image[40:, 55:edge - 1] = (60, 60, 60)
        image[40:, edge - 1] = (49, 49, 49) if shoulder else (60, 60, 60)
        image[40:, edge] = (36, 36, 36)
        image[40:, edge + 1:] = (30, 30, 30)
        return image

    mapper = ViewportMapper()
    without_shoulder_image = toolbar_with_shoulder(False)
    with_shoulder_image = toolbar_with_shoulder(True)
    gray = cv2.cvtColor(with_shoulder_image, cv2.COLOR_RGB2GRAY)
    gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    profile = np.mean(gradient, axis=0)
    shoulder_index = edge - 2
    dominant_peak = float(np.max(profile[edge - 1:edge + 1]))
    support = gradient[:, shoulder_index] >= mapper.MIN_EDGE_STRENGTH
    band_top = round(with_shoulder_image.shape[0] * 0.85)
    band_bottom = round(with_shoulder_image.shape[0] * 0.90)
    assert float(profile[shoulder_index]) >= mapper.MIN_EDGE_STRENGTH
    assert mapper._sustained_contrast(with_shoulder_image, shoulder_index, 1) >= (
        mapper.MIN_SUSTAINED_CONTRAST
    )
    assert float(np.mean(support)) >= mapper.MIN_EDGE_SUPPORT
    assert float(np.mean(support[band_top:band_bottom])) >= mapper.MIN_EDGE_SUPPORT
    assert float(profile[shoulder_index]) < dominant_peak * 0.75
    assert float(np.min(profile[edge - 1:edge + 1])) >= dominant_peak * 0.75

    without_shoulder = mapper.locate(without_shoulder_image)
    with_shoulder = mapper.locate(with_shoulder_image)

    assert with_shoulder.signature == without_shoulder.signature


def test_credible_edge_accepts_qualified_neighbor_when_plateau_peak_lacks_band_support() -> None:
    mapper = ViewportMapper()
    height = 1040
    width = 1920
    edge = 1824
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[:, :edge] = (80, 80, 80)
    image[:, edge:] = (20, 20, 20)
    gradient = np.zeros((height, „ù<∂âûÀk∫wµÁ@ÄÄÄÄÅπ¿πµïÖ∏°Öççï¡—ïë}ù…Öë•ïπ—mïëùïtÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q §(ÄÄÄÄ§(ÄÄÄÅÖÕÕï…–Ä¿∏ÿ¿ÄÙÅÖççï¡—ïë}Õ’¡¡Ω…–ÄÅµÖ¡¡ï»π5%9}}MUAA=IP((ÄÄÄÅµÖ¡¡ïë}ïëùîÄÙÅµÖ¡¡ï»π}ç…ïë•â±ï}ïëùî†(ÄÄÄÄÄÄÄÅÖççï¡—ïë}¡…Ωô•±î∞(ÄÄÄÄÄÄÄÅµÖ‡†–∞Å…Ω’πê°°ï•ù°–Ä®Ä¿∏¿ƒ§§∞(ÄÄÄÄÄÄÄÅµÖ‡†‘∞Å…Ω’πê°°ï•ù°–Ä®Ä¿∏»‘§§∞(ÄÄÄÄÄÄÄÄâ—•—±ïâÖ»à∞(ÄÄÄÄÄÄÄÅ•µÖùî∞(ÄÄÄÄÄÄÄÅÖççï¡—ïë}ù…Öë•ïπ–∞(ÄÄÄÄÄÄÄÄ¿∞(ÄÄÄÄÄÄÄÅÕ’¡¡Ω…—}âΩ’πëÃı—…Ö•±•πù}âΩ’πëÃ∞(ÄÄÄÄÄÄÄÅô’±±}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}U11}MUAA=IP∞(ÄÄÄÄ§((ÄÄÄÅÖÕÕï…–ÅµÖ¡¡ïë}ïëùîÄÙÙÅïëùî((ÄÄÄÅ—…Ö•±•πù}Ωπ±Â}ù…Öë•ïπ–ÄÙÅπ¿πÈï…ΩÃ†°°ï•ù°–∞Å›•ë—†§∞Åë—Â¡îıπ¿πô±ΩÖ–Ã»§(ÄÄÄÅ—…Ö•±•πù}Ωπ±Â}ù…Öë•ïπ—mïëùî∞Å—…Ö•±•πù}âΩ’πëÕl¡tÈ—…Ö•±•πù}âΩ’πëÕl≈utÄÙÄƒ¿¿∏¿(ÄÄÄÅ—…Ö•±•πù}Ωπ±Â}¡…Ωô•±îÄÙÅπ¿πµïÖ∏°—…Ö•±•πù}Ωπ±Â}ù…Öë•ïπ–∞ÅÖ·•ÃÙƒ§(ÄÄÄÅ—…Ö•±•πù}Ωπ±Â}Õ’¡¡Ω…–ÄÙÅô±ΩÖ–†(ÄÄÄÄÄÄÄÅπ¿πµïÖ∏°—…Ö•±•πù}Ωπ±Â}ù…Öë•ïπ—mïëùïtÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q §(ÄÄÄÄ§(ÄÄÄÅÖÕÕï…–Å—…Ö•±•πù}Ωπ±Â}Õ’¡¡Ω…–ÄÅµÖ¡¡ï»π5%9}Q%Q1	I}U11}MUAA=IP(ÄÄÄÅ›•—†Å¡Â—ïÕ–π…Ö•ÕïÃ°YÖ±’ï……Ω»∞ÅµÖ—ç†Ùâ—ΩºÅ›ïÖ¨à§Ë(ÄÄÄÄÄÄÄÅµÖ¡¡ï»π}ç…ïë•â±ï}ïëùî†(ÄÄÄÄÄÄÄÄÄÄÄÅ—…Ö•±•πù}Ωπ±Â}¡…Ωô•±î∞(ÄÄÄÄÄÄÄÄÄÄÄÅµÖ‡†–∞Å…Ω’πê°°ï•ù°–Ä®Ä¿∏¿ƒ§§∞(ÄÄÄÄÄÄÄÄÄÄÄÅµÖ‡†‘∞Å…Ω’πê°°ï•ù°–Ä®Ä¿∏»‘§§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ—•—±ïâÖ»à∞(ÄÄÄÄÄÄÄÄÄÄÄÅ•µÖùî∞(ÄÄÄÄÄÄÄÄÄÄÄÅ—…Ö•±•πù}Ωπ±Â}ù…Öë•ïπ–∞(ÄÄÄÄÄÄÄÄÄÄÄÄ¿∞(ÄÄÄÄÄÄÄÄÄÄÄÅÕ’¡¡Ω…—}âΩ’πëÃı—…Ö•±•πù}âΩ’πëÃ∞(ÄÄÄÄÄÄÄÄÄÄÄÅô’±±}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}U11}MUAA=IP∞(ÄÄÄÄÄÄÄÄ§(()ëïòÅ—ïÕ—}ç…ïë•â±ï}ïëùï}…ï©ïç—Õ}›ïÖ≠}—•—±ïâÖ…}ç…ΩÕÕ}çΩµâ•πÖ—•Ω∏†§Ä¥¯Å9ΩπîË(ÄÄÄÅµÖ¡¡ï»ÄÙÅY•ï›¡Ω…—5Ö¡¡ï»†§(ÄÄÄÅ°ï•ù°–ÄÙÄƒ¿Ã»(ÄÄÄÅ›•ë—†ÄÙÄƒ‰»¿(ÄÄÄÅïëùîÄÙÄƒ¿¿(ÄÄÄÅ—ΩΩ±âÖ…}±ïô–ÄÙÄƒ‡ƒ‰(ÄÄÄÅ—…Ö•±•πù}›•ë—†ÄÙÅµÖ‡†(ÄÄÄÄÄÄÄÄƒ∞Å…Ω’πê°—ΩΩ±âÖ…}±ïô–Ä®ÅµÖ¡¡ï»πQI%1%9}}MUAA=IQ}IQ%=8§(ÄÄÄÄ§(ÄÄÄÅ—…Ö•±•πù}âΩ’πëÃÄÙÄ°—ΩΩ±âÖ…}±ïô–Ä¥Å—…Ö•±•πù}›•ë—†∞Å—ΩΩ±âÖ…}±ïô–§(ÄÄÄÅ•µÖùîÄÙÅπ¿πïµ¡—‰†°°ï•ù°–∞Å›•ë—†∞ÄÃ§∞Åë—Â¡îıπ¿π’•π–‡§(ÄÄÄÅ•µÖùïlÈïëùïtÄÙÄ†»¿∞Ä»¿∞Ä»¿§(ÄÄÄÅ•µÖùïmïëùîÈtÄÙÄ†‡¿∞Ä‡¿∞Ä‡¿§(ÄÄÄÅù…Öë•ïπ–ÄÙÅπ¿πÈï…ΩÃ†°°ï•ù°–∞Å›•ë—†§∞Åë—Â¡îıπ¿πô±ΩÖ–Ã»§(ÄÄÄÅ—Ω—Ö±}Õ’¡¡Ω…–ÄÙÅ…Ω’πê°›•ë—†Ä®Ä¿∏–ƒ»‘§(ÄÄÄÅ—…Ö•±•πù}Õ’¡¡Ω…–ÄÙÅ…Ω’πê°—…Ö•±•πù}›•ë—†Ä®Ä¿∏»ÿ–§(ÄÄÄÅù…Öë•ïπ—mïëùî∞ÄÈ—Ω—Ö±}Õ’¡¡Ω…–Ä¥Å—…Ö•±•πù}Õ’¡¡Ω…—tÄÙÄƒ¿¿∏¿(ÄÄÄÅù…Öë•ïπ—l(ÄÄÄÄÄÄÄÅïëùî∞(ÄÄÄÄÄÄÄÅ—…Ö•±•πù}âΩ’πëÕl¡tÈ—…Ö•±•πù}âΩ’πëÕl¡tÄ¨Å—…Ö•±•πù}Õ’¡¡Ω…–∞(ÄÄÄÅtÄÙÄƒ¿¿∏¿(ÄÄÄÅ¡…Ωô•±îÄÙÅπ¿πµïÖ∏°ù…Öë•ïπ–∞ÅÖ·•ÃÙƒ§(ÄÄÄÅô’±±}Õ’¡¡Ω…–ÄÙÅô±ΩÖ–†(ÄÄÄÄÄÄÄÅπ¿πµïÖ∏°ù…Öë•ïπ—mïëùïtÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q §(ÄÄÄÄ§(ÄÄÄÅâΩ’πëïë}Õ’¡¡Ω…–ÄÙÅô±ΩÖ–†(ÄÄÄÄÄÄÄÅπ¿πµïÖ∏†(ÄÄÄÄÄÄÄÄÄÄÄÅù…Öë•ïπ—mïëùî∞Å—…Ö•±•πù}âΩ’πëÕl¡tÈ—…Ö•±•πù}âΩ’πëÕl≈ut(ÄÄÄÄÄÄÄÄÄÄÄÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q (ÄÄÄÄÄÄÄÄ§(ÄÄÄÄ§(ÄÄÄÅÖÕÕï…–Åô’±±}Õ’¡¡Ω…–Ä¯ÙÄ¿∏–¿(ÄÄÄÅÖÕÕï…–ÅâΩ’πëïë}Õ’¡¡Ω…–Ä¯ÙÄ¿∏»‘(ÄÄÄÅÖÕÕï…–Åô’±±}Õ’¡¡Ω…–ÄÄ¿∏‘‘(ÄÄÄÅÖÕÕï…–ÅâΩ’πëïë}Õ’¡¡Ω…–ÄÄ¿∏‰‘((ÄÄÄÅ›•—†Å¡Â—ïÕ–π…Ö•ÕïÃ°YÖ±’ï……Ω»∞ÅµÖ—ç†Ùâ—ΩºÅ›ïÖ¨à§Ë(ÄÄÄÄÄÄÄÅµÖ¡¡ï»π}ç…ïë•â±ï}ïëùî†(ÄÄÄÄÄÄÄÄÄÄÄÅ¡…Ωô•±î∞(ÄÄÄÄÄÄÄÄÄÄÄÅµÖ‡†–∞Å…Ω’πê°°ï•ù°–Ä®Ä¿∏¿ƒ§§∞(ÄÄÄÄÄÄÄÄÄÄÄÅ…Ω’πê°°ï•ù°–Ä®ÅµÖ¡¡ï»π5a}Q%Q1	I}MI!}IQ%=8§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ—•—±ïâÖ»à∞(ÄÄÄÄÄÄÄÄÄÄÄÅ•µÖùî∞(ÄÄÄÄÄÄÄÄÄÄÄÅù…Öë•ïπ–∞(ÄÄÄÄÄÄÄÄÄÄÄÄ¿∞(ÄÄÄÄÄÄÄÄÄÄÄÅÕ’¡¡Ω…—}âΩ’πëÃı—…Ö•±•πù}âΩ’πëÃ∞(ÄÄÄÄÄÄÄÄÄÄÄÅâΩ’πëïë}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}	=U9}MUAA=IP∞(ÄÄÄÄÄÄÄÄÄÄÄÅô’±±}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}U11}MUAA=IP∞(ÄÄÄÄÄÄÄÄ§(()ëïòÅ—ïÕ—}ç…ïë•â±ï}ïëùï}Öççï¡—Õ}°•ù°}çΩπ—…ÖÕ—}Öπ•µÖ—ïë}—•—±ïâÖ…}Õ’¡¡Ω…–†§Ä¥¯Å9ΩπîË(ÄÄÄÅµÖ¡¡ï»ÄÙÅY•ï›¡Ω…—5Ö¡¡ï»†§(ÄÄÄÅ°ï•ù°–ÄÙÄƒ¿Ã»(ÄÄÄÅ›•ë—†ÄÙÄƒ‰»¿(ÄÄÄÅïëùîÄÙÄÃ‰(ÄÄÄÅ—ΩΩ±âÖ…}±ïô–ÄÙÄƒ‡ƒ‰(ÄÄÄÅ—…Ö•±•πù}›•ë—†ÄÙÅµÖ‡†(ÄÄÄÄÄÄÄÄƒ∞Å…Ω’πê°—ΩΩ±âÖ…}±ïô–Ä®ÅµÖ¡¡ï»πQI%1%9}}MUAA=IQ}IQ%=8§(ÄÄÄÄ§(ÄÄÄÅ—…Ö•±•πù}âΩ’πëÃÄÙÄ°—ΩΩ±âÖ…}±ïô–Ä¥Å—…Ö•±•πù}›•ë—†∞Å—ΩΩ±âÖ…}±ïô–§(ÄÄÄÅ•µÖùîÄÙÅπ¿πïµ¡—‰†°°ï•ù°–∞Å›•ë—†∞ÄÃ§∞Åë—Â¡îıπ¿π’•π–‡§(ÄÄÄÅ•µÖùïlÈïëùïtÄÙÄ†»¿∞Ä»¿∞Ä»¿§(ÄÄÄÅ•µÖùïmïëùîÈtÄÙÄ†‰¿∞Ä‹¿∞Ä–¿§(ÄÄÄÅù…Öë•ïπ–ÄÙÅπ¿πÈï…ΩÃ†°°ï•ù°–∞Å›•ë—†§∞Åë—Â¡îıπ¿πô±ΩÖ–Ã»§(ÄÄÄÅù…Öë•ïπ—mïëùî∞ÄÈ…Ω’πê°›•ë—†Ä®Ä¿∏–ÿ•tÄÙÄƒ¿¿∏¿(ÄÄÄÅ¡…Ωô•±îÄÙÅπ¿πµïÖ∏°ù…Öë•ïπ–∞ÅÖ·•ÃÙƒ§((ÄÄÄÅô’±±}Õ’¡¡Ω…–ÄÙÅô±ΩÖ–†(ÄÄÄÄÄÄÄÅπ¿πµïÖ∏°ù…Öë•ïπ—mïëùïtÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q §(ÄÄÄÄ§(ÄÄÄÅâΩ’πëïë}Õ’¡¡Ω…–ÄÙÅô±ΩÖ–†(ÄÄÄÄÄÄÄÅπ¿πµïÖ∏†(ÄÄÄÄÄÄÄÄÄÄÄÅù…Öë•ïπ—mïëùî∞Å—…Ö•±•πù}âΩ’πëÕl¡tÈ—…Ö•±•πù}âΩ’πëÕl≈ut(ÄÄÄÄÄÄÄÄÄÄÄÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q (ÄÄÄÄÄÄÄÄ§(ÄÄÄÄ§(ÄÄÄÅÖÕÕï…–Åô’±±}Õ’¡¡Ω…–Ä¯ÙÅµÖ¡¡ï»π5%9}Q%Q1	I}9%5Q}U11}MUAA=IP(ÄÄÄÅÖÕÕï…–Åô’±±}Õ’¡¡Ω…–ÄÅµÖ¡¡ï»π5%9}Q%Q1	I}U11}MUAA=IP(ÄÄÄÅÖÕÕï…–ÅâΩ’πëïë}Õ’¡¡Ω…–ÄÅµÖ¡¡ï»π5%9}Q%Q1	I}	=U9}MUAA=IP(ÄÄÄÅÖÕÕï…–ÅµÖ¡¡ï»π}Õ’Õ—Ö•πïë}çΩπ—…ÖÕ–°•µÖùî∞Åïëùî∞Ä¿§Ä¯ÙÄ†(ÄÄÄÄÄÄÄÅµÖ¡¡ï»π5%9}Q%Q1	I}9%5Q}MUMQ%9}=9QIMP(ÄÄÄÄ§((ÄÄÄÅµÖ¡¡ïë}ïëùîÄÙÅµÖ¡¡ï»π}ç…ïë•â±ï}ïëùî†(ÄÄÄÄÄÄÄÅ¡…Ωô•±î∞(ÄÄÄÄÄÄÄÅµÖ‡†–∞Å…Ω’πê°°ï•ù°–Ä®Ä¿∏¿ƒ§§∞(ÄÄÄÄÄÄÄÅ…Ω’πê°°ï•ù°–Ä®ÅµÖ¡¡ï»π5a}Q%Q1	I}MI!}IQ%=8§∞(ÄÄÄÄÄÄÄÄâ—•—±ïâÖ»à∞(ÄÄÄÄÄÄÄÅ•µÖùî∞(ÄÄÄÄÄÄÄÅù…Öë•ïπ–∞(ÄÄÄÄÄÄÄÄ¿∞(ÄÄÄÄÄÄÄÅÕ’¡¡Ω…—}âΩ’πëÃı—…Ö•±•πù}âΩ’πëÃ∞(ÄÄÄÄÄÄÄÅâΩ’πëïë}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}	=U9}MUAA=IP∞(ÄÄÄÄÄÄÄÅô’±±}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}U11}MUAA=IP∞(ÄÄÄÄ§((ÄÄÄÅÖÕÕï…–ÅµÖ¡¡ïë}ïëùîÄÙÙÅïëùî(()ëïòÅ—ïÕ—}ç…ïë•â±ï}ïëùï}Öççï¡—Õ}¡Ö•…ïë}±Ω›}Õ’¡¡Ω…—}Öπ•µÖ—ïë}—•—±ïâÖ»†§Ä¥¯Å9ΩπîË(ÄÄÄÅµÖ¡¡ï»ÄÙÅY•ï›¡Ω…—5Ö¡¡ï»†§(ÄÄÄÅ°ï•ù°–ÄÙÄƒ¿Ã»(ÄÄÄÅ›•ë—†ÄÙÄƒ‰»¿(ÄÄÄÅïëùîÄÙÄÃ‰(ÄÄÄÅ—ΩΩ±âÖ…}±ïô–ÄÙÄƒ‡ƒ‰(ÄÄÄÅ—…Ö•±•πù}›•ë—†ÄÙÅµÖ‡†(ÄÄÄÄÄÄÄÄƒ∞Å…Ω’πê°—ΩΩ±âÖ…}±ïô–Ä®ÅµÖ¡¡ï»πQI%1%9}}MUAA=IQ}IQ%=8§(ÄÄÄÄ§(ÄÄÄÅ—…Ö•±•πù}âΩ’πëÃÄÙÄ°—ΩΩ±âÖ…}±ïô–Ä¥Å—…Ö•±•πù}›•ë—†∞Å—ΩΩ±âÖ…}±ïô–§(ÄÄÄÅ•µÖùîÄÙÅπ¿πïµ¡—‰†°°ï•ù°–∞Å›•ë—†∞ÄÃ§∞Åë—Â¡îıπ¿π’•π–‡§(ÄÄÄÅ•µÖùïlÈïëùïtÄÙÄ†»¿∞Ä»¿∞Ä»¿§(ÄÄÄÅ•µÖùïmïëùîÈtÄÙÄ†‰¿∞Ä‹¿∞Ä–¿§(ÄÄÄÅù…Öë•ïπ–ÄÙÅπ¿πÈï…ΩÃ†°°ï•ù°–∞Å›•ë—†§∞Åë—Â¡îıπ¿πô±ΩÖ–Ã»§(ÄÄÄÅù…Öë•ïπ—mïëùî∞ÄÈ…Ω’πê°›•ë—†Ä®Ä¿∏–ƒ‘•tÄÙÄƒ¿¿∏¿(ÄÄÄÅù…Öë•ïπ—mïëùîÄ¨Äƒ∞ÄÈ…Ω’πê°›•ë—†Ä®Ä¿∏–ƒƒ•tÄÙÄƒ¿¿∏¿(ÄÄÄÅ¡…Ωô•±îÄÙÅπ¿πµïÖ∏°ù…Öë•ïπ–∞ÅÖ·•ÃÙƒ§((ÄÄÄÅôΩ»Å…Ω‹Å•∏Ä°ïëùî∞ÅïëùîÄ¨Äƒ§Ë(ÄÄÄÄÄÄÄÅÕ’¡¡Ω…–ÄÙÅô±ΩÖ–†(ÄÄÄÄÄÄÄÄÄÄÄÅπ¿πµïÖ∏°ù…Öë•ïπ—m…Ω›tÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q §(ÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅÖÕÕï…–ÅÕ’¡¡Ω…–Ä¯ÙÅµÖ¡¡ï»π5%9}Q%Q1	I}9%5Q}A%I}U11}MUAA=IP(ÄÄÄÄÄÄÄÅÖÕÕï…–ÅÕ’¡¡Ω…–ÄÅµÖ¡¡ï»π5%9}Q%Q1	I}9%5Q}U11}MUAA=IP(ÄÄÄÄÄÄÄÅÖÕÕï…–ÅµÖ¡¡ï»π}Õ’Õ—Ö•πïë}çΩπ—…ÖÕ–°•µÖùî∞Å…Ω‹∞Ä¿§Ä¯ÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÅµÖ¡¡ï»π5%9}Q%Q1	I}9%5Q}MUMQ%9}=9QIMP(ÄÄÄÄÄÄÄÄ§((ÄÄÄÅµÖ¡¡ïë}ïëùîÄÙÅµÖ¡¡ï»π}ç…ïë•â±ï}ïëùî†(ÄÄÄÄÄÄÄÅ¡…Ωô•±î∞(ÄÄÄÄÄÄÄÅµÖ‡†–∞Å…Ω’πê°°ï•ù°–Ä®Ä¿∏¿ƒ§§∞(ÄÄÄÄÄÄÄÅ…Ω’πê°°ï•ù°–Ä®ÅµÖ¡¡ï»π5a}Q%Q1	I}MI!}IQ%=8§∞(ÄÄÄÄÄÄÄÄâ—•—±ïâÖ»à∞(ÄÄÄÄÄÄÄÅ•µÖùî∞(ÄÄÄÄÄÄÄÅù…Öë•ïπ–∞(ÄÄÄÄÄÄÄÄ¿∞(ÄÄÄÄÄÄÄÅÕ’¡¡Ω…—}âΩ’πëÃı—…Ö•±•πù}âΩ’πëÃ∞(ÄÄÄÄÄÄÄÅâΩ’πëïë}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}	=U9}MUAA=IP∞(ÄÄÄÄÄÄÄÅô’±±}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}U11}MUAA=IP∞(ÄÄÄÄ§((ÄÄÄÅÖÕÕï…–ÅµÖ¡¡ïë}ïëùîÄÙÙÅïëùî(()ëïòÅ—ïÕ—}ç…ïë•â±ï}ïëùï}Öççï¡—Õ}πïÖ…}ô’±±}—ΩΩ±âÖ…}›•—°}Õ—…Ωπù}±Ω›ï…}âÖπê†§Ä¥¯Å9ΩπîË(ÄÄÄÅµÖ¡¡ï»ÄÙÅY•ï›¡Ω…—5Ö¡¡ï»†§(ÄÄÄÅ°ï•ù°–ÄÙÄƒ¿Ã»(ÄÄÄÅ›•ë—†ÄÙÄƒ‰»¿(ÄÄÄÅïëùîÄÙÄƒ‡ƒ‡(ÄÄÄÅ•µÖùîÄÙÅπ¿πïµ¡—‰†°°ï•ù°–∞Å›•ë—†∞ÄÃ§∞Åë—Â¡îıπ¿π’•π–‡§(ÄÄÄÅ•µÖùïlË∞ÄÈïëùïtÄÙÄ†‰¿∞Ä‹¿∞Ä–¿§(ÄÄÄÅ•µÖùïlË∞ÅïëùîÈtÄÙÄ†»¿∞Ä»¿∞Ä»¿§(ÄÄÄÅù…Öë•ïπ–ÄÙÅπ¿πÈï…ΩÃ†°°ï•ù°–∞Å›•ë—†§∞Åë—Â¡îıπ¿πô±ΩÖ–Ã»§(ÄÄÄÅÕ’¡¡Ω…—ïë}…Ω›ÃÄÙÅ…Ω’πê°°ï•ù°–Ä®Ä¿∏ÿÿ–§(ÄÄÄÅù…Öë•ïπ—lÈÕ’¡¡Ω…—ïë}…Ω›Ã∞ÅïëùïtÄÙÄƒ¿¿∏¿(ÄÄÄÅâÖπë}—Ω¿∞ÅâÖπë}âΩ——Ω¥ÄÙÄ†(ÄÄÄÄÄÄÄÅ…Ω’πê°°ï•ù°–Ä®Åô…Öç—•Ω∏§ÅôΩ»Åô…Öç—•Ω∏Å•∏ÅµÖ¡¡ï»πQ==1	I}MUAA=IQ}	9(ÄÄÄÄ§(ÄÄÄÅÕ’¡¡Ω…—ïë}âÖπë}âΩ——Ω¥ÄÙÅâÖπë}—Ω¿Ä¨Å…Ω’πê†(ÄÄÄÄÄÄÄÄ°âÖπë}âΩ——Ω¥Ä¥ÅâÖπë}—Ω¿§Ä®Ä¿∏‹‡(ÄÄÄÄ§(ÄÄÄÅù…Öë•ïπ—mâÖπë}—Ω¿ÈÕ’¡¡Ω…—ïë}âÖπë}âΩ——Ω¥∞ÅïëùïtÄÙÄƒ¿¿∏¿(ÄÄÄÅ¡…Ωô•±îÄÙÅπ¿πµïÖ∏°ù…Öë•ïπ–∞ÅÖ·•ÃÙ¿§((ÄÄÄÅô’±±}Õ’¡¡Ω…–ÄÙÅô±ΩÖ–†(ÄÄÄÄÄÄÄÅπ¿πµïÖ∏°ù…Öë•ïπ—lË∞ÅïëùïtÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q §(ÄÄÄÄ§(ÄÄÄÅâΩ’πëïë}Õ’¡¡Ω…–ÄÙÅô±ΩÖ–†(ÄÄÄÄÄÄÄÅπ¿πµïÖ∏†(ÄÄÄÄÄÄÄÄÄÄÄÅù…Öë•ïπ—mâÖπë}—Ω¿ÈâÖπë}âΩ——Ω¥∞Åïëùït(ÄÄÄÄÄÄÄÄÄÄÄÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q (ÄÄÄÄÄÄÄÄ§(ÄÄÄÄ§(ÄÄÄÅÖÕÕï…–Åô’±±}Õ’¡¡Ω…–ÄÅµÖ¡¡ï»π5%9}}MUAA=IP(ÄÄÄÅÖÕÕï…–Åô’±±}Õ’¡¡Ω…–Ä¯ÙÅµÖ¡¡ï»π5%9}Q==1	I}MQI=9}	9}U11}MUAA=IP(ÄÄÄÅÖÕÕï…–ÅâΩ’πëïë}Õ’¡¡Ω…–Ä¯ÙÄ¿∏‹‡(ÄÄÄÅÖÕÕï…–ÅâΩ’πëïë}Õ’¡¡Ω…–Ä¯ÙÅµÖ¡¡ï»π5%9}Q==1	I}MQI=9}	9}MUAA=IP((ÄÄÄÅµÖ¡¡ïë}ïëùîÄÙÅµÖ¡¡ï»π}ç…ïë•â±ï}ïëùî†(ÄÄÄÄÄÄÄÅ¡…Ωô•±î∞(ÄÄÄÄÄÄÄÅ…Ω’πê°›•ë—†Ä®Ä¿∏ÿ‘§∞(ÄÄÄÄÄÄÄÅµ•∏†(ÄÄÄÄÄÄÄÄÄÄÄÅ›•ë—†Ä¥Ä»∞(ÄÄÄÄÄÄÄÄÄÄÄÅ…Ω’πê°›•ë—†Ä®Ä†ƒ∏¿Ä¥ÅµÖ¡¡ï»π=UQI}	=II}a1UM%=9}IQ%=8§§∞(ÄÄÄÄÄÄÄÄ§∞(ÄÄÄÄÄÄÄÄâ—ΩΩ±âÖ»à∞(ÄÄÄÄÄÄÄÅ•µÖùî∞(ÄÄÄÄÄÄÄÅù…Öë•ïπ–∞(ÄÄÄÄÄÄÄÄƒ∞(ÄÄÄÄÄÄÄÅÕ’¡¡Ω…—}âΩ’πëÃÙ°âÖπë}—Ω¿∞ÅâÖπë}âΩ——Ω¥§∞(ÄÄÄÄÄÄÄÅâΩ’πëïë}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q==1	I}	=U9}MUAA=IP∞(ÄÄÄÄÄÄÄÅ¡…ïôï…}—…Ö•±•πù}çÖπë•ëÖ—îıQ…’î∞(ÄÄÄÄ§((ÄÄÄÅÖÕÕï…–ÅµÖ¡¡ïë}ïëùîÄÙÙÅïëùî(()ëïòÅ—ïÕ—}ç…ïë•â±ï}ïëùï}¡…ïôï…Õ}Öπ•µÖ—ïë}—Ω¡}—•—±ïâÖ…}ΩŸï…}›ïÖ≠}°’ë}ïëùî†§Ä¥¯Å9ΩπîË(ÄÄÄÅµÖ¡¡ï»ÄÙÅY•ï›¡Ω…—5Ö¡¡ï»†§(ÄÄÄÅ°ï•ù°–ÄÙÄƒ¿Ã»(ÄÄÄÅ›•ë—†ÄÙÄƒ‰»¿(ÄÄÄÅïëùîÄÙÄÃ‰(ÄÄÄÅ±Ω›ï…}°’ë}ïëùîÄÙÄ‰‘(ÄÄÄÅ—ΩΩ±âÖ…}±ïô–ÄÙÄƒ‡ƒ‰(ÄÄÄÅ—…Ö•±•πù}›•ë—†ÄÙÅµÖ‡†(ÄÄÄÄÄÄÄÄƒ∞Å…Ω’πê°—ΩΩ±âÖ…}±ïô–Ä®ÅµÖ¡¡ï»πQI%1%9}}MUAA=IQ}IQ%=8§(ÄÄÄÄ§(ÄÄÄÅ—…Ö•±•πù}âΩ’πëÃÄÙÄ°—ΩΩ±âÖ…}±ïô–Ä¥Å—…Ö•±•πù}›•ë—†∞Å—ΩΩ±âÖ…}±ïô–§(ÄÄÄÅ•µÖùîÄÙÅπ¿πïµ¡—‰†°°ï•ù°–∞Å›•ë—†∞ÄÃ§∞Åë—Â¡îıπ¿π’•π–‡§(ÄÄÄÅ•µÖùïlÈïëùïtÄÙÄ†»¿∞Ä»¿∞Ä»¿§(ÄÄÄÅ•µÖùïmïëùîÈ±Ω›ï…}°’ë}ïëùïtÄÙÄ†‰¿∞Ä‹¿∞Ä–¿§(ÄÄÄÅ•µÖùïm±Ω›ï…}°’ë}ïëùîÈtÄÙÄ†ƒ»¿∞Äƒ¿¿∞Ä‹¿§(ÄÄÄÅù…Öë•ïπ–ÄÙÅπ¿πÈï…ΩÃ†°°ï•ù°–∞Å›•ë—†§∞Åë—Â¡îıπ¿πô±ΩÖ–Ã»§(ÄÄÄÅù…Öë•ïπ—mïëùî∞ÄÈ…Ω’πê°›•ë—†Ä®Ä¿∏‘Ã–•tÄÙÄƒ¿¿∏¿(ÄÄÄÅù…Öë•ïπ—mïëùîÄ¨Äƒ∞ÄÈ…Ω’πê°›•ë—†Ä®Ä¿∏‘»‹•tÄÙÄƒ¿¿∏¿(ÄÄÄÅù…Öë•ïπ—m±Ω›ï…}°’ë}ïëùî∞ÄÈ…Ω’πê°›•ë—†Ä®Ä¿∏‘‘–•tÄÙÄƒ¿¿∏¿(ÄÄÄÅ›ïÖ≠}âÖπë}Õ—Ω¿ÄÙÅ—…Ö•±•πù}âΩ’πëÕl¡tÄ¨Å…Ω’πê°—…Ö•±•πù}›•ë—†Ä®Ä¿∏Ã‘§(ÄÄÄÅù…Öë•ïπ—l(ÄÄÄÄÄÄÄÅ±Ω›ï…}°’ë}ïëùî∞(ÄÄÄÄÄÄÄÅ—…Ö•±•πù}âΩ’πëÕl¡tÈ›ïÖ≠}âÖπë}Õ—Ω¿∞(ÄÄÄÅtÄÙÄƒ¿¿∏¿(ÄÄÄÅ¡…Ωô•±îÄÙÅπ¿πµïÖ∏°ù…Öë•ïπ–∞ÅÖ·•ÃÙƒ§((ÄÄÄÅ—Ω¡}âΩ’πëïë}Õ’¡¡Ω…–ÄÙÅô±ΩÖ–†(ÄÄÄÄÄÄÄÅπ¿πµïÖ∏†(ÄÄÄÄÄÄÄÄÄÄÄÅù…Öë•ïπ—mïëùî∞Å—…Ö•±•πù}âΩ’πëÕl¡tÈ—…Ö•±•πù}âΩ’πëÕl≈ut(ÄÄÄÄÄÄÄÄÄÄÄÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q (ÄÄÄÄÄÄÄÄ§(ÄÄÄÄ§(ÄÄÄÅ±Ω›ï…}âΩ’πëïë}Õ’¡¡Ω…–ÄÙÅô±ΩÖ–†(ÄÄÄÄÄÄÄÅπ¿πµïÖ∏†(ÄÄÄÄÄÄÄÄÄÄÄÅù…Öë•ïπ—l(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅ±Ω›ï…}°’ë}ïëùî∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅ—…Ö•±•πù}âΩ’πëÕl¡tÈ—…Ö•±•πù}âΩ’πëÕl≈t∞(ÄÄÄÄÄÄÄÄÄÄÄÅt(ÄÄÄÄÄÄÄÄÄÄÄÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q (ÄÄÄÄÄÄÄÄ§(ÄÄÄÄ§(ÄÄÄÅÖÕÕï…–Å—Ω¡}âΩ’πëïë}Õ’¡¡Ω…–ÄÅµÖ¡¡ï»π5%9}Q%Q1	I}	=U9}MUAA=IP(ÄÄÄÅÖÕÕï…–Å±Ω›ï…}âΩ’πëïë}Õ’¡¡Ω…–Ä¯ÙÅµÖ¡¡ï»π5%9}Q%Q1	I}	=U9}MUAA=IP(ÄÄÄÅÖÕÕï…–Å±Ω›ï…}âΩ’πëïë}Õ’¡¡Ω…–ÄÅµÖ¡¡ï»π5%9}}MUAA=IP((ÄÄÄÅµÖ¡¡ïë}ïëùîÄÙÅµÖ¡¡ï»π}ç…ïë•â±ï}ïëùî†(ÄÄÄÄÄÄÄÅ¡…Ωô•±î∞(ÄÄÄÄÄÄÄÅµÖ‡†–∞Å…Ω’πê°°ï•ù°–Ä®Ä¿∏¿ƒ§§∞(ÄÄÄÄÄÄÄÅ…Ω’πê°°ï•ù°–Ä®ÅµÖ¡¡ï»π5a}Q%Q1	I}MI!}IQ%=8§∞(ÄÄÄÄÄÄÄÄâ—•—±ïâÖ»à∞(ÄÄÄÄÄÄÄÅ•µÖùî∞(ÄÄÄÄÄÄÄÅù…Öë•ïπ–∞(ÄÄÄÄÄÄÄÄ¿∞(ÄÄÄÄÄÄÄÅÕ’¡¡Ω…—}âΩ’πëÃı—…Ö•±•πù}âΩ’πëÃ∞(ÄÄÄÄÄÄÄÅâΩ’πëïë}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}	=U9}MUAA=IP∞(ÄÄÄÄÄÄÄÅô’±±}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}U11}MUAA=IP∞(ÄÄÄÄ§((ÄÄÄÅÖÕÕï…–ÅµÖ¡¡ïë}ïëùîÄÙÙÅïëùî((ÄÄÄÅ¡Ö…—•Ö±}âÖπë}Õ—Ω¿ÄÙÅ—…Ö•±•πù}âΩ’πëÕl¡tÄ¨Å…Ω’πê°—…Ö•±•πù}›•ë—†Ä®Ä¿∏Ã¿§(ÄÄÄÅôΩ»Å…Ω‹Å•∏Ä°ïëùî∞ÅïëùîÄ¨Äƒ§Ë(ÄÄÄÄÄÄÄÅù…Öë•ïπ—m…Ω‹∞Å—…Ö•±•πù}âΩ’πëÕl¡tÈ¡Ö…—•Ö±}âÖπë}Õ—Ω¡tÄÙÄƒ¿¿∏¿(ÄÄÄÅ¡…Ωô•±îÄÙÅπ¿πµïÖ∏°ù…Öë•ïπ–∞ÅÖ·•ÃÙƒ§(ÄÄÄÅÖÕÕï…–Åô±ΩÖ–†(ÄÄÄÄÄÄÄÅπ¿πµïÖ∏†(ÄÄÄÄÄÄÄÄÄÄÄÅù…Öë•ïπ—mïëùî∞Å—…Ö•±•πù}âΩ’πëÕl¡tÈ—…Ö•±•πù}âΩ’πëÕl≈ut(ÄÄÄÄÄÄÄÄÄÄÄÄ¯ÙÅµÖ¡¡ï»π5%9}}MQI9Q (ÄÄÄÄÄÄÄÄ§(ÄÄÄÄ§Ä¯ÙÅµÖ¡¡ï»π5%9}Q%Q1	I}	=U9}MUAA=IP((ÄÄÄÅµÖ¡¡ïë}¡Ö…—•Ö±}âÖπë}ïëùîÄÙÅµÖ¡¡ï»π}ç…ïë•â±ï}ïëùî†(ÄÄÄÄÄÄÄÅ¡…Ωô•±î∞(ÄÄÄÄÄÄÄÅµÖ‡†–∞Å…Ω’πê°°ï•ù°–Ä®Ä¿∏¿ƒ§§∞(ÄÄÄÄÄÄÄÅ…Ω’πê°°ï•ù°–Ä®ÅµÖ¡¡ï»π5a}Q%Q1	I}MI!}IQ%=8§∞(ÄÄÄÄÄÄÄÄâ—•—±ïâÖ»à∞(ÄÄÄÄÄÄÄÅ•µÖùî∞(ÄÄÄÄÄÄÄÅù…Öë•ïπ–∞(ÄÄÄÄÄÄÄÄ¿∞(ÄÄÄÄÄÄÄÅÕ’¡¡Ω…—}âΩ’πëÃı—…Ö•±•πù}âΩ’πëÃ∞(ÄÄÄÄÄÄÄÅâΩ’πëïë}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}	=U9}MUAA=IP∞(ÄÄÄÄÄÄÄÅô’±±}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}U11}MUAA=IP∞(ÄÄÄÄ§((ÄÄÄÅÖÕÕï…–ÅµÖ¡¡ïë}¡Ö…—•Ö±}âÖπë}ïëùîÄÙÙÅïëùî(()ëïòÅ—ïÕ—}ç…ïë•â±ï}ïëùï}¡…ïôï…Õ}’π•≈’ï}—Ω¡}—•—±ïâÖ…}ΩŸï…}ëïπÕï}—’—Ω…•Ö±}—ï·—’…î†§Ä¥¯Å9ΩπîË(ÄÄÄÅµÖ¡¡ï»ÄÙÅY•ï›¡Ω…—5Ö¡¡ï»†§(ÄÄÄÅ°ï•ù°–ÄÙÄƒ¿Ã»(ÄÄÄÅ›•ë—†ÄÙÄƒ‰»¿(ÄÄÄÅïëùîÄÙÄÃ‰(ÄÄÄÅ±Ω›ï…}ïëùïÃÄÙÄ†ÿ¿∞Ä‹‘∞Ä‰¿∞Äƒ¿‘§(ÄÄÄÅ—ΩΩ±âÖ…}±ïô–ÄÙÄƒ‡ƒ‰(ÄÄÄÅ—…Ö•±•πù}›•ë—†ÄÙÅµÖ‡†(ÄÄÄÄÄÄÄÄƒ∞Å…Ω’πê°—ΩΩ±âÖ…}±ïô–Ä®ÅµÖ¡¡ï»πQI%1%9}}MUAA=IQ}IQ%=8§(ÄÄÄÄ§(ÄÄÄÅ—…Ö•±•πù}âΩ’πëÃÄÙÄ°—ΩΩ±âÖ…}±ïô–Ä¥Å—…Ö•±•πù}›•ë—†∞Å—ΩΩ±âÖ…}±ïô–§(ÄÄÄÅ•µÖùîÄÙÅπ¿πïµ¡—‰†°°ï•ù°–∞Å›•ë—†∞ÄÃ§∞Åë—Â¡îıπ¿π’•π–‡§(ÄÄÄÅâΩ’πëÖ…•ïÃÄÙÄ°ïëùî∞Ä©±Ω›ï…}ïëùïÃ§(ÄÄÄÅçΩ±Ω…ÃÄÙÄ†(ÄÄÄÄÄÄÄÄ†»¿∞Ä»¿∞Ä»¿§∞(ÄÄÄÄÄÄÄÄ†‰¿∞Ä‹¿∞Ä–¿§∞(ÄÄÄÄÄÄÄÄ†ƒ–¿∞Äƒ»¿∞Ä‰¿§∞(ÄÄÄÄÄÄÄÄ†‹¿∞Ä‰¿∞Äƒ»¿§∞(ÄÄÄÄÄÄÄÄ†ƒ‘¿∞ÄƒÃ¿∞Äƒ¿¿§∞(ÄÄÄÄÄÄÄÄ†‡¿∞Äƒ¿¿∞ÄƒÃ¿§∞(ÄÄÄÄ§(ÄÄÄÅÕ—Ö…–ÄÙÄ¿(ÄÄÄÅôΩ»ÅÕ—Ω¿∞ÅçΩ±Ω»Å•∏ÅÈ•¿°âΩ’πëÖ…•ïÃ∞ÅçΩ±Ω…ÕlË¥≈t∞ÅÕ—…•ç–ıQ…’î§Ë(ÄÄÄÄÄÄÄÅ•µÖùïmÕ—Ö…–ÈÕ—Ω¡tÄÙÅçΩ±Ω»(ÄÄÄÄÄÄÄÅÕ—Ö…–ÄÙÅÕ—Ω¿(ÄÄÄÅ•µÖùïmÕ—Ö…–ÈtÄÙÅçΩ±Ω…Õl¥≈t(ÄÄÄÅù…Öë•ïπ–ÄÙÅπ¿πÈï…ΩÃ†°°ï•ù°–∞Å›•ë—†§∞Åë—Â¡îıπ¿πô±ΩÖ–Ã»§(ÄÄÄÅù…Öë•ïπ—mïëùî∞ÄÈ…Ω’πê°›•ë—†Ä®Ä¿∏ÿ¿•tÄÙÄƒ¿¿∏¿(ÄÄÄÅù…Öë•ïπ—l(ÄÄÄÄÄÄÄÅïëùî∞(ÄÄÄÄÄÄÄÅ—…Ö•±•πù}âΩ’πëÕl¡tÈ—…Ö•±•πù}âΩ’πëÕl¡tÄ¨Å…Ω’πê°—…Ö•±•πù}›•ë—†Ä®Ä¿∏–¿§∞(ÄÄÄÅtÄÙÄƒ¿¿∏¿(ÄÄÄÅôΩ»Å±Ω›ï…}ïëùîÅ•∏Å±Ω›ï…}ïëùïÃË(ÄÄÄÄÄÄÄÅù…Öë•ïπ—m±Ω›ï…}ïëùî∞ÄÈ…Ω’πê°›•ë—†Ä®Ä¿∏‡¿•tÄÙÄƒ¿¿∏¿(ÄÄÄÄÄÄÄÅù…Öë•ïπ—l(ÄÄÄÄÄÄÄÄÄÄÄÅ±Ω›ï…}ïëùî∞(ÄÄÄÄÄÄÄÄÄÄÄÅ—…Ö•±•πù}âΩ’πëÕl¡tÈ—…Ö•±•πù}âΩ’πëÕl≈t∞(ÄÄÄÄÄÄÄÅtÄÙÄƒ¿¿∏¿(ÄÄÄÅ¡…Ωô•±îÄÙÅπ¿πµïÖ∏°ù…Öë•ïπ–∞ÅÖ·•ÃÙƒ§((ÄÄÄÅµÖ¡¡ïë}ïëùîÄÙÅµÖ¡¡ï»π}ç…ïë•â±ï}ïëùî†(ÄÄÄÄÄÄÄÅ¡…Ωô•±î∞(ÄÄÄÄÄÄÄÅµÖ‡†–∞Å…Ω’πê°°ï•ù°–Ä®Ä¿∏¿ƒ§§∞(ÄÄÄÄÄÄÄÅ…Ω’πê°°ï•ù°–Ä®ÅµÖ¡¡ï»π5a}Q%Q1	I}MI!}IQ%=8§∞(ÄÄÄÄÄÄÄÄâ—•—±ïâÖ»à∞(ÄÄÄÄÄÄÄÅ•µÖùî∞(ÄÄÄÄÄÄÄÅù…Öë•ïπ–∞(ÄÄÄÄÄÄÄÄ¿∞(ÄÄÄÄÄÄÄÅÕ’¡¡Ω…—}âΩ’πëÃı—…Ö•±•πù}âΩ’πëÃ∞(ÄÄÄÄÄÄÄÅâΩ’πëïë}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}	=U9}MUAA=IP∞(ÄÄÄÄÄÄÄÅô’±±}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}U11}MUAA=IP∞(ÄÄÄÄ§((ÄÄÄÅÖÕÕï…–ÅµÖ¡¡ïë}ïëùîÄÙÙÅïëùî(()ëïòÅ—ïÕ—}ç…ïë•â±ï}ïëùï}¡…ïôï…Õ}’π•≈’ï}—Ω¡}—•—±ïâÖ…}ΩŸï…}çΩµ¡Öç—}âÖ——±ï}°’ë}ç±’Õ—ï»†§Ä¥¯Å9ΩπîË(ÄÄÄÅµÖ¡¡ï»ÄÙÅY•ï›¡Ω…—5Ö¡¡ï»†§(ÄÄÄÅ°ï•ù°–ÄÙÄƒ¿Ã»(ÄÄÄÅ›•ë—†ÄÙÄƒ‰»¿(ÄÄÄÅïëùîÄÙÄÃ‰(ÄÄÄÅ±Ω›ï…}ïëùïÃÄÙÄ†‡ÿ∞Ä‰‘∞Äƒƒ‘§(ÄÄÄÅ—ΩΩ±âÖ…}±ïô–ÄÙÄƒ‡ƒ‰(ÄÄÄÅ—…Ö•±•πù}›•ë—†ÄÙÅµÖ‡†(ÄÄÄÄÄÄÄÄƒ∞Å…Ω’πê°—ΩΩ±âÖ…}±ïô–Ä®ÅµÖ¡¡ï»πQI%1%9}}MUAA=IQ}IQ%=8§(ÄÄÄÄ§(ÄÄÄÅ—…Ö•±•πù}âΩ’πëÃÄÙÄ°—ΩΩ±âÖ…}±ïô–Ä¥Å—…Ö•±•πù}›•ë—†∞Å—ΩΩ±âÖ…}±ïô–§(ÄÄÄÅ•µÖùîÄÙÅπ¿πïµ¡—‰†°°ï•ù°–∞Å›•ë—†∞ÄÃ§∞Åë—Â¡îıπ¿π’•π–‡§(ÄÄÄÅâΩ’πëÖ…•ïÃÄÙÄ°ïëùî∞Ä©±Ω›ï…}ïëùïÃ§(ÄÄÄÅçΩ±Ω…ÃÄÙÄ†(ÄÄÄÄÄÄÄÄ†»¿∞Ä»¿∞Ä»¿§∞(ÄÄÄÄÄÄÄÄ†‰¿∞Ä‹¿∞Ä–¿§∞(ÄÄÄÄÄÄÄÄ†ƒ–¿∞Äƒ»¿∞Ä‰¿§∞(ÄÄÄÄÄÄÄÄ†‹¿∞Ä‰¿∞Äƒ»¿§∞(ÄÄÄÄÄÄÄÄ†ƒ‘¿∞ÄƒÃ¿∞Äƒ¿¿§∞(ÄÄÄÄ§(ÄÄÄÅÕ—Ö…–ÄÙÄ¿(ÄÄÄÅôΩ»ÅÕ—Ω¿∞ÅçΩ±Ω»Å•∏ÅÈ•¿°âΩ’πëÖ…•ïÃ∞ÅçΩ±Ω…ÕlË¥≈t∞ÅÕ—…•ç–ıQ…’î§Ë(ÄÄÄÄÄÄÄÅ•µÖùïmÕ—Ö…–ÈÕ—Ω¡tÄÙÅçΩ±Ω»(ÄÄÄÄÄÄÄÅÕ—Ö…–ÄÙÅÕ—Ω¿(ÄÄÄÅ•µÖùïmÕ—Ö…–ÈtÄÙÅçΩ±Ω…Õl¥≈t(ÄÄÄÅù…Öë•ïπ–ÄÙÅπ¿πÈï…ΩÃ†°°ï•ù°–∞Å›•ë—†§∞Åë—Â¡îıπ¿πô±ΩÖ–Ã»§(ÄÄÄÅù…Öë•ïπ—mïëùî∞ÄÈ…Ω’πê°›•ë—†Ä®Ä¿∏‹‹•tÄÙÄƒ¿¿∏¿(ÄÄÄÅù…Öë•ïπ—mïëùî∞Å—…Ö•±•πù}âΩ’πëÕl¡tÈ—…Ö•±•πù}âΩ’πëÕl≈utÄÙÄƒ¿¿∏¿(ÄÄÄÅôΩ»Å±Ω›ï…}ïëùîÅ•∏Å±Ω›ï…}ïëùïÃË(ÄÄÄÄÄÄÄÅù…Öë•ïπ—m±Ω›ï…}ïëùî∞ÄÈ…Ω’πê°›•ë—†Ä®Ä¿∏ÿ¿•tÄÙÄƒ¿¿∏¿(ÄÄÄÄÄÄÄÅù…Öë•ïπ—l(ÄÄÄÄÄÄÄÄÄÄÄÅ±Ω›ï…}ïëùî∞(ÄÄÄÄÄÄÄÄÄÄÄÅ—…Ö•±•πù}âΩ’πëÕl¡tÈ—…Ö•±•πù}âΩ’πëÕl≈t∞(ÄÄÄÄÄÄÄÅtÄÙÄƒ¿¿∏¿(ÄÄÄÅ¡…Ωô•±îÄÙÅπ¿πµïÖ∏°ù…Öë•ïπ–∞ÅÖ·•ÃÙƒ§((ÄÄÄÅµÖ¡¡ïë}ïëùîÄÙÅµÖ¡¡ï»π}ç…ïë•â±ï}ïëùî†(ÄÄÄÄÄÄÄÅ¡…Ωô•±î∞(ÄÄÄÄÄÄÄÅµÖ‡†–∞Å…Ω’πê°°ï•ù°–Ä®Ä¿∏¿ƒ§§∞(ÄÄÄÄÄÄÄÅ…Ω’πê°°ï•ù°–Ä®ÅµÖ¡¡ï»π5a}Q%Q1	I}MI!}IQ%=8§∞(ÄÄÄÄÄÄÄÄâ—•—±ïâÖ»à∞(ÄÄÄÄÄÄÄÅ•µÖùî∞(ÄÄÄÄÄÄÄÅù…Öë•ïπ–∞(ÄÄÄÄÄÄÄÄ¿∞(ÄÄÄÄÄÄÄÅÕ’¡¡Ω…—}âΩ’πëÃı—…Ö•±•πù}âΩ’πëÃ∞(ÄÄÄÄÄÄÄÅâΩ’πëïë}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}	=U9}MUAA=IP∞(ÄÄÄÄÄÄÄÅô’±±}Õ’¡¡Ω…—}—°…ïÕ°Ω±êıµÖ¡¡ï»π5%9}Q%Q1	I}U11}MUAA=IP∞(ÄÄÄÄ§((ÄÄÄÅÖÕÕï…–ÅµÖ¡¡ïë}ïëùîÄÙÙÅïëùî(()ëïòÅ—ïÕ—}±ΩçÖ—ï}•ùπΩ…ïÕ}Õ—…Ωπù}Õ¡Ö…Õï}ë•Õ—…Öç—Ω…Õ}Ωπ}âΩ—°}Ö·ïÃ†§Ä¥¯Å9ΩπîË(ÄÄÄÅ•µÖùîÄÙÅÕÂπ—°ï—•ç}±ë¡±ÖÂï»†§(ÄÄÄÅ•µÖùïlƒ»¿Ë‘»¿∞Äƒ‘¿Ë‰¿¡tÄÙÄ†»–‘∞Ä»–‘∞Ä»–‘§(ÄÄÄÅ•µÖùïl‘‹¿Ë‰‹¿∞Äƒ–‘¿Ëƒ‹¿¡tÄÙÄ†»–‘∞Ä»–‘∞Ä»–‘§((ÄÄÄÅµÖ¡¡ï»ÄÙÅY•ï›¡Ω…—5Ö¡¡ï»†§(ÄÄÄÅµÖ¡¡•πúÄÙÅµÖ¡¡ï»π±ΩçÖ—î°•µÖùî§((ÄÄÄÅÖÕÕï…–ÅµÖ¡¡•πúπ—•—±ïâÖ…}âΩ——Ω¥Å•∏Å…Öπùî†Ã‘∞Ä–ÿ§(ÄÄÄÅÖÕÕï…–ÅµÖ¡¡•πúπ—ΩΩ±âÖ…}±ïô–Å•∏Å…Öπùî†ƒ‡ƒ‡∞Äƒ‡Ã»§((ÄÄÄÅ±ïÖë•πù}›•ππï»ÄÙÅ•µÖùîπçΩ¡‰†§(ÄÄÄÅ—…Ö•±•πù}›•ππï»ÄÙÅ•µÖùîπçΩ¡‰†§(ÄÄÄÅ±ïÖë•πù}›•ππï…l–¿Ë∞Äƒ‡»—tÄÙÄ†»–¿∞Ä»–¿∞Ä»–¿§(ÄÄÄÅ—…Ö•±•πù}›•ππï…l–¿Ë∞Äƒ‡»—tÄÙÄ†»»¿∞Ä»»¿∞Ä»»¿§((ÄÄÄÅ±ïÖë•πù}µÖ¡¡•πúÄÙÅµÖ¡¡ï»π±ΩçÖ—î°±ïÖë•πù}›•ππï»§(ÄÄÄÅ—…Ö•±•πù}µÖ¡¡•πúÄÙÅµÖ¡¡ï»π±ΩçÖ—î°—…Ö•±•πù}›•ππï»§((ÄÄÄÅÖÕÕï…–Å±ïÖë•πù}µÖ¡¡•πúπÕ•ùπÖ—’…îÄÙÙÅ—…Ö•±•πù}µÖ¡¡•πúπÕ•ùπÖ—’…î(ÄÄÄÅÖÕÕï…–ÅµÖ¡¡ï»π±ΩçÖ—î°ÕÂπ—°ï—•ç}±ë¡±ÖÂï»°—ΩΩ±âÖ…}±ïô–Ùƒ‡»ÿ§§πÕ•ùπÖ—’…îÄÑÙÅ±ïÖë•πù}µÖ¡¡•πúπÕ•ùπÖ—’…î(