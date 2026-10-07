// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief Blit raw frames from stdin into a fullscreen X window, scaled by the GPU.
 *
 * Why a purpose-built presenter: both mpv and ffplay are built around files or demuxed
 * streams, and their latency/queueing is fatal for an HMD -- measured, ffplay consumed a
 * live 60 fps stream and put 1-2 frames per second on the glass; mpv reached ~3.6 with
 * its cache disabled. Nausea is latency you can see.
 *
 * Why XRender rather than XShmPutImage: the panel is 3840x1200 and the renderer produces a
 * smaller image (rendering 4.6 M pixels/frame in Python caps the frame rate), so something
 * has to scale. Doing that on the CPU means either pushing 18.4 MB/frame through a pipe or
 * upscaling in software -- both cap the pipeline near 50 fps, measured. Here the frame goes
 * over the pipe at its native (small) size and the GPU scales it into the window:
 *
 *   renderer -> ffmpeg (rgb24 -> bgra only, no scaling) -> xpresent WxH OUT_W OUT_H
 *
 * Frames must already be in the byte order a depth-24 little-endian X server wants
 * natively, so filling the source pixmap is a memcpy.
 *
 * Usage:
 *   xpresent IN_W IN_H OUT_W OUT_H [hide_cursor]
 *
 * Prints the achieved rate to stderr every two seconds; exits when stdin ends.
 *
 * Build: cc -O2 -o tools/xpresent tools/xpresent.c -lX11 -lXext -lXrender
 */

#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/Xrender.h>
#include <X11/extensions/XShm.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ipc.h>
#include <sys/shm.h>
#include <time.h>
#include <unistd.h>

static int
x_error_handler(Display *dpy, XErrorEvent *e)
{
	char msg[256] = {0};
	XGetErrorText(dpy, e->error_code, msg, sizeof msg - 1);
	fprintf(stderr, "xpresent: X error on request %d.%d: %s (resource 0x%lx)\n", e->request_code,
	        e->minor_code, msg, e->resourceid);
	return 0;
}

static int
read_full(int fd, void *buf, size_t n)
{
	size_t got = 0;
	while (got < n) {
		const ssize_t r = read(fd, (char *)buf + got, n - got);
		if (r == 0) {
			return got == 0 ? 0 : -1;
		}
		if (r < 0) {
			if (errno == EINTR) {
				continue;
			}
			return -1;
		}
		got += (size_t)r;
	}
	return 1;
}

int
main(int argc, char **argv)
{
	const int in_w = argc > 1 ? atoi(argv[1]) : 1600;
	const int in_h = argc > 2 ? atoi(argv[2]) : 500;
	const int out_w = argc > 3 ? atoi(argv[3]) : 3840;
	const int out_h = argc > 4 ? atoi(argv[4]) : 1200;
	const int hide_cursor = argc > 5 ? atoi(argv[5]) : 1;

	XSetErrorHandler(x_error_handler);
	Display *dpy = XOpenDisplay(NULL);
	if (dpy == NULL) {
		fprintf(stderr, "xpresent: cannot open display\n");
		return 1;
	}
	const int scr = DefaultScreen(dpy);
	Visual *vis = DefaultVisual(dpy, scr);
	const int depth = DefaultDepth(dpy, scr);

	int ev_base, err_base;
	if (!XRenderQueryExtension(dpy, &ev_base, &err_base)) {
		fprintf(stderr, "xpresent: XRender unavailable\n");
		return 1;
	}

	XSetWindowAttributes at;
	memset(&at, 0, sizeof at);
	at.override_redirect = True;  // no window manager may resize, decorate or restack us
	at.background_pixel = BlackPixel(dpy, scr);
	Window win = XCreateWindow(dpy, RootWindow(dpy, scr), 0, 0, (unsigned)out_w, (unsigned)out_h, 0, depth,
	                           InputOutput, vis, CWOverrideRedirect | CWBackPixel, &at);
	XMapRaised(dpy, win);
	if (hide_cursor) {
		char empty[1] = {0};
		Pixmap pm = XCreateBitmapFromData(dpy, win, empty, 1, 1);
		XColor black = {0};
		Cursor cur = XCreatePixmapCursor(dpy, pm, pm, &black, &black, 0, 0);
		XDefineCursor(dpy, win, cur);
	}
	XSync(dpy, False);

	// Source pixmap the client fills with XPutImage. MIT-SHM pixmaps are not implemented by
	// this X server (ShmCreatePixmap returns BadImplementation), and the payload is small
	// now that the GPU does the scaling, so an ordinary socket copy is cheap enough.
	Pixmap src_pixmap = XCreatePixmap(dpy, win, (unsigned)in_w, (unsigned)in_h, (unsigned)depth);
	char *buffer = malloc((size_t)in_w * (size_t)in_h * 4);
	XImage *img = XCreateImage(dpy, vis, (unsigned)depth, ZPixmap, 0, buffer, (unsigned)in_w, (unsigned)in_h, 32, 0);
	if (img == NULL) {
		fprintf(stderr, "xpresent: XCreateImage failed\n");
		return 1;
	}
	GC gc = XCreateGC(dpy, src_pixmap, 0, NULL);

	XRenderPictFormat *fmt = XRenderFindVisualFormat(dpy, vis);
	fprintf(stderr, "xpresent: visual 0x%lx depth %d -> pictformat %p\n", XVisualIDFromVisual(vis), depth, (void *)fmt);
	if (fmt == NULL) {
		fprintf(stderr, "xpresent: no XRender format for this visual\n");
		return 1;
	}
	Picture src_pic = XRenderCreatePicture(dpy, src_pixmap, fmt, 0, NULL);
	XSync(dpy, False);
	Picture dst_pic = XRenderCreatePicture(dpy, win, fmt, 0, NULL);
	XSync(dpy, False);
	// Scale on the GPU: the transform maps the small source over the whole window.
	XTransform t;
	memset(&t, 0, sizeof t);
	t.matrix[0][0] = XDoubleToFixed((double)out_w / (double)in_w);
	t.matrix[1][1] = XDoubleToFixed((double)out_h / (double)in_h);
	t.matrix[2][2] = XDoubleToFixed(1.0);
	XRenderSetPictureTransform(dpy, src_pic, &t);
	XRenderSetPictureFilter(dpy, src_pic, FilterBilinear, NULL, 0);

	fprintf(stderr, "xpresent: %dx%d -> %dx%d (XRender, GPU scaled), stride %d, %d bpp\n", in_w, in_h, out_w, out_h,
	        img->bytes_per_line, img->bits_per_pixel);

	const size_t row_bytes = (size_t)in_w * 4;  // bgra
	char *staging = malloc(row_bytes);
	unsigned long frames = 0, report_frames = 0;
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	double report_start = (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;

	for (;;) {
		if (img->bytes_per_line == (int)row_bytes) {
			const int r = read_full(STDIN_FILENO, buffer, row_bytes * (size_t)in_h);
			if (r <= 0) {
				break;
			}
		} else {
			int ok = 1;
			for (int y = 0; y < in_h; y++) {
				if (read_full(STDIN_FILENO, staging, row_bytes) <= 0) {
					ok = 0;
					break;
				}
				memcpy(buffer + (size_t)y * (size_t)img->bytes_per_line, staging, row_bytes);
			}
			if (!ok) {
				break;
			}
		}
		XPutImage(dpy, src_pixmap, gc, img, 0, 0, 0, 0, (unsigned)in_w, (unsigned)in_h);
		XRenderComposite(dpy, PictOpSrc, src_pic, None, dst_pic, 0, 0, 0, 0, 0, 0, (unsigned)out_w, (unsigned)out_h);
		XFlush(dpy);  // no queue: what was rendered last is what is shown next
		frames++;
		report_frames++;
		clock_gettime(CLOCK_MONOTONIC, &ts);
		const double now = (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
		if (now - report_start >= 2.0) {
			fprintf(stderr, "xpresent: %.1f fps\n", (double)report_frames / (now - report_start));
			report_frames = 0;
			report_start = now;
		}
	}

	fprintf(stderr, "xpresent: stdin ended after %lu frames\n", frames);
	XRenderFreePicture(dpy, src_pic);
	XRenderFreePicture(dpy, dst_pic);
	XFreePixmap(dpy, src_pixmap);
	XDestroyImage(img);
	XCloseDisplay(dpy);
	return 0;
}
