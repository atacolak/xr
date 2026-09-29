package sh.colak.xrconsole.recorder;

enum PreviewSource {
    RGB("RGB"),
    GRAY_LEFT("L GRAY"),
    GRAY_RIGHT("R GRAY");

    final String label;
    PreviewSource(String label) { this.label = label; }

    PreviewSource next() {
        switch (this) {
            case RGB: return GRAY_LEFT;
            case GRAY_LEFT: return GRAY_RIGHT;
            default: return RGB;
        }
    }

    boolean isGray() { return this != RGB; }
}
