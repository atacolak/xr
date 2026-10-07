// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief Blit raw frames from stdin into a fullscreen X window, immediately.
 *
 * Why this exists: this is an HMD presenter, not a video player. Both mpv and ffplay
 * are designed around files or demuxed streams, and their latency/queueing is fatal
 * here -- measured, ffplay consumed a live 60 fps stream yet put 1-2 frames per second
 * on the glass, and mpv only reached ~3.6 with its demuxer cache disabled. Nausea is
 * just latency you can see.
 *
 * So there is no demuxer, no decoder, no cache and no vsync queue: read a frame, blit it,
 * flush, repeat. Frames are expected in the byte order a depth-24 little-endian X server
 * wants natively (BGRX = ffmpeg's `bgra`), so the blit is a memcpy with no conversion.
 *
 *   ffmpeg -f rawvideo -pix_fmt rgb24 -s 1920x600 -r 60 -i - \
 *          -vf scale=3840:1200 -pix_fmt bgra -f rawvideo - | xpresent 3840 1200
 *
 * Prints the achieved rate to stderr every two seconds; exits when stdin ends.
 *
 * Build: cc -O2 -o tools/xpresent tools/xpresent.c -lX11 -lXext
 */

#include <X11/Xlib.h>
#include <X11/Xutil.h>
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
	int w = argc > 1 ? atoi(argv[1]) : 3840;
	int h = argc > 2 ? atoi(argv[2]) : 1200;
	const int hide_cursor = argc > 3 ? atoi(argv[3]) : 1;

	Display *dpy = XOpenDisplay(NULL);
	if (dpy == NULL) {
		fprintf(stderr, "xpresent: cannot open display\n");
		return 1;
	}
	const int scr = DefaultScreen(dpy);
	Visual *vis = DefaultVisual(dpy, scr);
	const int depth = DefaultDepth(dpy, scr);

	XSetWindowAttributes at;
	memset(&at, 0, sizeof at);
	at.override_redirect = True;  // no window manager may resize, decorate or restack us
	at.background_pixel = BlackPixel(dpy, scr);
	Window win = XCreateWindow(dpy, RootWindow(dpy, scr), 0, 0, (unsigned)w, (unsigned)h, 0, depth, InputOutput, vis,
	                           CWOverrideRedirect | CWBackPixel, &at);
	XMapRaised(dpy, win);
	if (hide_cursor) {
		// An HMD has nowhere sensible to draw a pointer.
		char empty[1] = {0};
		Pixmap pm = XCreateBitmapFromData(dpy, win, empty, 1, 1);
		XColor black = {0};
		Cursor cur = XCreatePixmapCursor(dpy, pm, pm, &black, &black, 0, 0);
		XDefineCursor(dpy, win, cur);
	}
	XSync(dpy, False);

	XShmSegmentInfo shm;
	memset(&shm, 0, sizeof shm);
	XImage *img = XShmCreateImage(dpy, vis, (unsigned)depth, ZPixmap, NULL, &shm, (unsigned)w, (unsigned)h);
	if (img == NULL) {
		fprintf(stderr, "xpresent: XShmCreateImage failed (MIT-SHM unavailable?)\n");
		return 1;
	}
	shm.shmid = shmget(IPC_PRIVATE, (size_t)img->bytes_per_line * (size_t)h, IPC_CREAT | 0600);
	if (shm.shmid < 0) {
		fprintf(stderr, "xpresent: shmget failed: %s\n", strerror(errno));
		return 1;
	}
	shm.shmaddr = img->data = shmat(shm.shmid, NULL, 0);
	shm.readOnly = False;
	if (!XShmAttach(dpy, &shm)) {
		fprintf(stderr, "xpresent: XShmAttach failed\n");
		return 1;
	}
	shmctl(shm.shmid, IPC_RMID, NULL);  // freed when the last detach happens

	GC gc = XCreateGC(dpy, win, 0, NULL);
	fprintf(stderr, "xpresent: %dx%d, XImage stride %d bytes, %d bpp\n", w, h, img->bytes_per_line, img->bits_per_pixel);

	const size_t row_bytes = (size_t)w * 4;  // bgra
	char *staging = malloc(row_bytes);
	unsigned long frames = 0, report_frames = 0;
	double report_start = 0.0;
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	report_start = (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;

	for (;;) {
		if (img->bytes_per_line == (int)row_bytes) {
			const int r = read_full(STDIN_FILENO, img->data, row_bytes * (size_t)h);
			if (r <= 0) {
				break;
			}
		} else {
			// X server wants padding: copy row by row instead of assuming a tight pack.
			int ok = 1;
			for (int y = 0; y < h; y++) {
				if (read_full(STDIN_FILENO, staging, row_bytes) <= 0) {
					ok = 0;
					break;
				}
				memcpy(img->data + (size_t)y * (size_t)img->bytes_per_line, staging, row_bytes);
			}
			if (!ok) {
				break;
			}
		}
		XShmPutImage(dpy, win, gc, img, 0, 0, 0, 0, (unsigned)w, (unsigned)h, False);
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
	XShmDetach(dpy, &shm);
	XDestroyImage(img);
	shmdt(shm.shmaddr);
	XCloseDisplay(dpy);
	return 0;
}
