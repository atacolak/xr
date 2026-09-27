package sh.colak.xrconsole.recorder;

final class Yuv {
    static native void argbToNv12(int[] argb, int width, int height, byte[] nv12);

    static int nv12Size(int w, int h) {
        return w * h + w * h / 2;
    }
}
