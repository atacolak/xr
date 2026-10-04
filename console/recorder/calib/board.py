"""ChArUco target. Square length is 1 board unit unless overridden."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

DICTS = {
    "4x4_50": cv2.aruco.DICT_4X4_50,
    "4x4_100": cv2.aruco.DICT_4X4_100,
    "5x5_50": cv2.aruco.DICT_5X5_50,
    "5x5_100": cv2.aruco.DICT_5X5_100,
}


@dataclass(frozen=True)
class BoardSpec:
    squares_x: int = 8
    squares_y: int = 5
    square_length: float = 1.0
    marker_length: float = 0.75
    dict_name: str = "4x4_50"
    legacy_pattern: bool = False

    def opencv(self) -> cv2.aruco.CharucoBoard:
        if self.dict_name not in DICTS:
            raise ValueError(f"unknown dict {self.dict_name}; want {sorted(DICTS)}")
        dictionary = cv2.aruco.getPredefinedDictionary(DICTS[self.dict_name])
        board = cv2.aruco.CharucoBoard(
            (self.squares_x, self.squares_y),
            float(self.square_length),
            float(self.marker_length),
            dictionary,
        )
        board.setLegacyPattern(self.legacy_pattern)
        return board

    def to_json(self) -> dict:
        d = asdict(self)
        d["inner_corners"] = (self.squares_x - 1) * (self.squares_y - 1)
        d["units"] = "board_squares" if self.square_length == 1.0 else "user"
        return d


def generate_image(spec: BoardSpec, px_per_square: int = 160, margin: int = 40) -> np.ndarray:
    """Exact square pixels. Do not stretch."""
    w = spec.squares_x * px_per_square + 2 * margin
    h = spec.squares_y * px_per_square + 2 * margin
    return spec.opencv().generateImage((w, h), marginSize=margin, borderBits=1)


def letterbox(gray: np.ndarray, sw: int, sh: int) -> np.ndarray:
    h, w = gray.shape[:2]
    scale = min(sw / w, sh / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_NEAREST)
    canvas = np.zeros((sh, sw), dtype=np.uint8)
    x0 = (sw - nw) // 2
    y0 = (sh - nh) // 2
    canvas[y0 : y0 + nh, x0 : x0 + nw] = resized
    return canvas


def save_png(spec: BoardSpec, path, px_per_square: int = 160) -> None:
    from PIL import Image

    img = generate_image(spec, px_per_square=px_per_square)
    Image.fromarray(img).save(path)


def show_fullscreen(spec: BoardSpec, px_per_square: int = 160) -> int:
    """Fullscreen ChArUco. Escape quits. Letterboxed so squares stay square."""
    import os
    import tkinter as tk

    from PIL import Image, ImageTk

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("no DISPLAY; use: carina_calib.py target --png board.png")
        return 2
    gray = generate_image(spec, px_per_square=px_per_square)
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.configure(bg="black")
    root.bind("<Escape>", lambda _e: root.destroy())
    root.bind("q", lambda _e: root.destroy())
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    framed = letterbox(gray, sw, sh)
    photo = ImageTk.PhotoImage(Image.fromarray(framed))
    lbl = tk.Label(root, image=photo, bg="black", borderwidth=0, highlightthickness=0)
    lbl.image = photo
    lbl.pack(fill="both", expand=True)
    hint = tk.Label(
        root,
        text="wear luma  ·  vary distance and tilt  ·  both eyes  ·  Esc quits",
        fg="#888888",
        bg="black",
        font=("sans-serif", 14),
    )
    hint.place(relx=0.5, rely=0.98, anchor="s")
    root.mainloop()
    return 0
