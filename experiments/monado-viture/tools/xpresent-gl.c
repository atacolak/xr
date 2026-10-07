// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief Upload raw BGRA frames from stdin as a GL texture and present them
 *        scaled into a fullscreen override-redirect X window.
 *
 * Sibling of tools/xpresent.c: that path is a CPU XShmPutImage blit and tops
 * out near 60 fps at 3840x1200. This path lets GL do the scale and, when
 * GLX_EXT_swap_control is present, lets the panel's refresh pace the loop.
 *
 *   ffmpeg ... -pix_fmt bgra -f rawvideo - | xpresent-gl IN_W IN_H OUT_W OUT_H
 *
 * Prints the achieved rate to stderr every two seconds; exits when stdin ends.
 *
 * Build: cc -O2 -Wall -o tools/xpresent-gl tools/xpresent-gl.c -lGL -lX11
 */

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
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

static void
die(const char *msg)
{
	fprintf(stderr, "xpresent-gl: %s\n", msg);
	exit(1);
}

static int
has_glx_ext(const char *exts, const char *name)
{
	const size_t n = strlen(name);
	const char *p = exts;
	if (exts == NULL) {
		return 0;
	}
	while ((p = strstr(p, name)) != NULL) {
		if ((p == exts || p[-1] == ' ') && (p[n] == '\0' || p[n] == ' ')) {
			return 1;
		}
		p += n;
	}
	return 0;
}

static void
hide_window_cursor(Display *dpy, Window win)
{
	char empty[1] = {0};
	Pixmap pm = XCreateBitmapFromData(dpy, win, empty, 1, 1);
	XColor black = {0};
	Cursor cur = XCreatePixmapCursor(dpy, pm, pm, &black, &black, 0, 0);
	XDefineCursor(dpy, win, cur);
	XFreeCursor(dpy, cur);
	XFreePixmap(dpy, pm);
}

int
main(int argc, char **argv)
{
	if (argc < 5) {
		fprintf(stderr, "usage: xpresent-gl IN_W IN_H OUT_W OUT_H [hide_cursor]\n");
		return 1;
	}

	const int in_w = atoi(argv[1]);
	const int in_h = atoi(argv[2]);
	const int out_w = atoi(argv[3]);
	const int out_h = atoi(argv[4]);
	const int hide_cursor = argc > 5 ? atoi(argv[5]) : 1;
	if (in_w <= 0 || in_h <= 0 || out_w <= 0 || out_h <= 0) {
		die("dimensions must be positive");
	}

	Display *dpy = XOpenDisplay(NULL);
	if (dpy == NULL) {
		die("cannot open display");
	}
	const int scr = DefaultScreen(dpy);

	static const int fb_attr[] = {
	    GLX_X_RENDERABLE, True,
	    GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
	    GLX_RENDER_TYPE, GLX_RGBA_BIT,
	    GLX_X_VISUAL_TYPE, GLX_TRUE_COLOR,
	    GLX_RED_SIZE, 8,
	    GLX_GREEN_SIZE, 8,
	    GLX_BLUE_SIZE, 8,
	    GLX_DOUBLEBUFFER, True,
	    None,
	};
	int n_cfg = 0;
	GLXFBConfig *cfg = glXChooseFBConfig(dpy, scr, fb_attr, &n_cfg);
	if (cfg == NULL || n_cfg < 1) {
		die("no double-buffered RGBA GLX FBConfig");
	}
	GLXFBConfig fbc = cfg[0];
	XFree(cfg);

	XVisualInfo *vi = glXGetVisualFromFBConfig(dpy, fbc);
	if (vi == NULL) {
		die("glXGetVisualFromFBConfig failed");
	}

	XSetWindowAttributes at;
	memset(&at, 0, sizeof at);
	at.override_redirect = True;
	at.background_pixel = BlackPixel(dpy, scr);
	at.border_pixel = 0;
	at.colormap = XCreateColormap(dpy, RootWindow(dpy, scr), vi->visual, AllocNone);
	at.event_mask = StructureNotifyMask;
	Window win = XCreateWindow(dpy, RootWindow(dpy, scr), 0, 0, (unsigned)out_w, (unsigned)out_h, 0, vi->depth,
	                           InputOutput, vi->visual,
	                           CWOverrideRedirect | CWBackPixel | CWBorderPixel | CWColormap | CWEventMask, &at);
	XStoreName(dpy, win, "xpresent-gl");
	XClassHint class_hint;
	class_hint.res_name = "xpresent-gl";
	class_hint.res_class = "xpresent-gl";
	XSetClassHint(dpy, win, &class_hint);
	XMapRaised(dpy, win);
	if (hide_cursor) {
		hide_window_cursor(dpy, win);
	}

	for (;;) {
		XEvent ev;
		XNextEvent(dpy, &ev);
		if (ev.type == MapNotify && ev.xmap.window == win) {
			break;
		}
	}
	XSync(dpy, False);
	fprintf(stderr, "xpresent-gl: window 0x%lx %dx%d <- %dx%d\n", (unsigned long)win, out_w, out_h, in_w, in_h);

	GLXWindow glxwin = glXCreateWindow(dpy, fbc, win, NULL);
	if (glxwin == None) {
		die("glXCreateWindow failed");
	}
	GLXContext ctx = glXCreateNewContext(dpy, fbc, GLX_RGBA_TYPE, NULL, True);
	if (ctx == NULL) {
		die("glXCreateNewContext failed");
	}
	if (!glXMakeContextCurrent(dpy, glxwin, glxwin, ctx)) {
		die("glXMakeContextCurrent failed");
	}
	XFree(vi);

	const char *exts = glXQueryExtensionsString(dpy, scr);
	PFNGLXSWAPINTERVALEXTPROC glXSwapIntervalEXT = NULL;
	if (has_glx_ext(exts, "GLX_EXT_swap_control")) {
		glXSwapIntervalEXT =
		    (PFNGLXSWAPINTERVALEXTPROC)glXGetProcAddress((const GLubyte *)"glXSwapIntervalEXT");
	}
	if (glXSwapIntervalEXT != NULL) {
		glXSwapIntervalEXT(dpy, glxwin, 1);
	} else {
		fprintf(stderr, "xpresent-gl: vsync unavailable (no GLX_EXT_swap_control)\n");
	}

	const size_t frame_bytes = (size_t)in_w * (size_t)in_h * 4u;
	unsigned char *pixels = malloc(frame_bytes);
	if (pixels == NULL) {
		die("out of memory");
	}

	glDisable(GL_DEPTH_TEST);
	glDisable(GL_LIGHTING);
	glDisable(GL_BLEND);
	glEnable(GL_TEXTURE_2D);
	glViewport(0, 0, out_w, out_h);
	glMatrixMode(GL_PROJECTION);
	glLoadIdentity();
	glOrtho(0.0, (GLdouble)out_w, (GLdouble)out_h, 0.0, -1.0, 1.0);
	glMatrixMode(GL_MODELVIEW);
	glLoadIdentity();
	glPixelStorei(GL_UNPACK_ALIGNMENT, 1);

	GLuint tex = 0;
	glGenTextures(1, &tex);
	glBindTexture(GL_TEXTURE_2D, tex);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, in_w, in_h, 0, GL_BGRA, GL_UNSIGNED_BYTE, NULL);

	unsigned long frames = 0, report_frames = 0;
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	double report_start = (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;

	for (;;) {
		while (XPending(dpy)) {
			XEvent ev;
			XNextEvent(dpy, &ev);
		}
		const int r = read_full(STDIN_FILENO, pixels, frame_bytes);
		if (r <= 0) {
			break;
		}
		glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, in_w, in_h, GL_BGRA, GL_UNSIGNED_BYTE, pixels);
		glBegin(GL_QUADS);
		glTexCoord2f(0.f, 0.f);
		glVertex2f(0.f, 0.f);
		glTexCoord2f(1.f, 0.f);
		glVertex2f((GLfloat)out_w, 0.f);
		glTexCoord2f(1.f, 1.f);
		glVertex2f((GLfloat)out_w, (GLfloat)out_h);
		glTexCoord2f(0.f, 1.f);
		glVertex2f(0.f, (GLfloat)out_h);
		glEnd();
		glXSwapBuffers(dpy, glxwin);

		frames++;
		report_frames++;
		clock_gettime(CLOCK_MONOTONIC, &ts);
		const double now = (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
		if (now - report_start >= 2.0) {
			fprintf(stderr, "xpresent-gl: %.1f fps\n", (double)report_frames / (now - report_start));
			report_frames = 0;
			report_start = now;
		}
	}

	fprintf(stderr, "xpresent-gl: stdin ended after %lu frames\n", frames);
	free(pixels);
	glXMakeContextCurrent(dpy, None, None, NULL);
	glXDestroyContext(dpy, ctx);
	glXDestroyWindow(dpy, glxwin);
	XDestroyWindow(dpy, win);
	XCloseDisplay(dpy);
	return 0;
}
