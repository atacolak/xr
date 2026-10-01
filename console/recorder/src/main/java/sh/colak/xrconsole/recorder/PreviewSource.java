package sh.colak.xrconsole.recorder;

enum PreviewSource {
    RGB("RGB"),
    GRAY_LEFT("L GRAY"),
    GRAY_RIGHT("R GRAY"),
    GRAY_STEREO("L|R");

    final String label;
    PreviewSource(String label) { this.label = label; }

    PreviewSource next() {
        switch (this) {
            case RGB: return GRAY_LEFT;
            case GRAY_LEFT: return GRAY_RIGHT;
            case GRAY_RIGHT: return GRAY_STEREO;
            default: return RGB;
        }
    }

    boolean isGray() { return this != RGB; }
    boolean isStereo() { return this == GRAY_STEREO; }

    static PreviewSource fromExtra(String s) {
        if (s == null) return RGB;
        switch (s.toLowerCase()) {
            case "l": case "left": case "lgray": case "gray": return GRAY_LEFT;
            case "r": case "right": case "rgray": return GRAY_RIGHT;
            case "lr": case "stereo": case "l|r": return GRAY_STEREO;
            default: return RGB;
        }
    }
}
